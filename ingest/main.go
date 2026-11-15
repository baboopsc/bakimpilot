// Command ingest receives raw flight telemetry from ground control stations,
// reduces it to a flight summary, and forwards it to the BakımPilot API.
//
// Why a separate Go service (D-033): telemetry uploads are large (thousands of
// samples per flight) and bursty. A small, statically linked Go binary parses
// and aggregates them cheaply and concurrently, so Django only ever receives a
// few numbers per flight.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const maxBodyBytes = 20 << 20 // 20 MB, several hours of 1 Hz samples

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func newMux(fwd *Forwarder, log *slog.Logger) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("POST /v1/telemetry", func(w http.ResponseWriter, r *http.Request) {
		var t Telemetry
		dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBodyBytes))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&t); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON: " + err.Error()})
			return
		}
		summary, err := Summarize(t)
		if err != nil {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"error": err.Error()})
			return
		}
		status, err := fwd.Send(r.Context(), summary)
		var perm *PermanentError
		switch {
		case errors.As(err, &perm):
			log.Warn("api rejected flight", "flight", t.FlightID, "status", perm.Status, "body", perm.Body)
			writeJSON(w, http.StatusUnprocessableEntity, map[string]any{
				"error": "rejected by API", "api_status": perm.Status, "detail": perm.Body,
			})
		case err != nil:
			log.Error("forward failed", "flight", t.FlightID, "err", err)
			writeJSON(w, http.StatusBadGateway, map[string]string{"error": "API unavailable, retry later"})
		default:
			log.Info("flight ingested", "flight", t.FlightID, "tail", t.TailNumber,
				"samples", len(t.Samples), "api_status", status)
			writeJSON(w, http.StatusAccepted, map[string]any{"summary": summary, "duplicate": status == http.StatusOK})
		}
	})
	return mux
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	token := os.Getenv("INGEST_TOKEN")
	if token == "" {
		log.Error("INGEST_TOKEN is required")
		os.Exit(1)
	}
	fwd := &Forwarder{
		URL:      env("API_URL", "http://api:8000/api/ingest/flights/"),
		Token:    token,
		Client:   &http.Client{Timeout: 10 * time.Second},
		Attempts: 4,
		Backoff:  500 * time.Millisecond,
	}
	srv := &http.Server{
		Addr:              env("LISTEN_ADDR", ":8080"),
		Handler:           newMux(fwd, log),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       60 * time.Second,
		WriteTimeout:      60 * time.Second,
	}

	// Graceful shutdown: finish in-flight uploads on SIGTERM (docker stop).
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		log.Info("ingest listening", "addr", srv.Addr, "api", fwd.URL)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("server error", "err", err)
			os.Exit(1)
		}
	}()
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdown)
}
