package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

var t0 = time.Date(2026, 3, 1, 8, 0, 0, 0, time.UTC)

// flight builds 1-sample-per-minute telemetry: ground, `air` minutes airborne, ground.
func flight(air int) Telemetry {
	var s []Sample
	add := func(min int, ground bool) {
		s = append(s, Sample{T: t0.Add(time.Duration(min) * time.Minute), OnGround: ground,
			EngineTempC: 90 + float64(min%5), VibrationG: 0.4, FuelFlowLPH: 12})
	}
	add(0, true)
	for m := 1; m <= air; m++ {
		add(m, false)
	}
	add(air+1, true)
	return Telemetry{FlightID: "GS-1", TailNumber: "TB2-T001", Samples: s}
}

func TestSummarizeBasicFlight(t *testing.T) {
	s, err := Summarize(flight(120))
	if err != nil {
		t.Fatal(err)
	}
	if !s.TakeoffAt.Equal(t0.Add(time.Minute)) || !s.LandingAt.Equal(t0.Add(120*time.Minute)) {
		t.Fatalf("takeoff/landing wrong: %v %v", s.TakeoffAt, s.LandingAt)
	}
	if s.Cycles != 1 || s.AvgVibrationG != 0.4 || s.MaxEngineTempC != 94 {
		t.Fatalf("unexpected summary %+v", s)
	}
	// 12 L/h for 121 minutes of samples (0..121) = 24.2 L
	if s.FuelUsedL != 24.2 {
		t.Fatalf("fuel = %v, want 24.2", s.FuelUsedL)
	}
}

func TestTouchAndGoCountsTwoCycles(t *testing.T) {
	f := flight(10)
	f.Samples[5].OnGround = true // touches down mid-flight
	s, err := Summarize(f)
	if err != nil || s.Cycles != 2 {
		t.Fatalf("cycles = %d, err = %v", s.Cycles, err)
	}
}

func TestDataGapIsNotCountedAsFuel(t *testing.T) {
	f := flight(10)
	for i := 6; i < len(f.Samples); i++ { // 1-hour telemetry dropout after sample 5
		f.Samples[i].T = f.Samples[i].T.Add(time.Hour)
	}
	s, _ := Summarize(f)
	if s.FuelUsedL > 3 {
		t.Fatalf("fuel %v includes the data gap", s.FuelUsedL)
	}
}

func TestSummarizeRejectsBadInput(t *testing.T) {
	never := flight(3)
	for i := range never.Samples {
		never.Samples[i].OnGround = true
	}
	shuffled := flight(3)
	shuffled.Samples[1], shuffled.Samples[2] = shuffled.Samples[2], shuffled.Samples[1]

	cases := map[string]struct {
		in   Telemetry
		want error
	}{
		"no samples":   {Telemetry{FlightID: "x", TailNumber: "y"}, ErrNoSamples},
		"never flew":   {never, ErrNotAirborne},
		"out of order": {shuffled, ErrTimeOrder},
	}
	for name, c := range cases {
		if _, err := Summarize(c.in); !errors.Is(err, c.want) {
			t.Errorf("%s: got %v, want %v", name, err, c.want)
		}
	}
}

func newForwarder(url string) *Forwarder {
	return &Forwarder{URL: url, Token: "secret", Client: http.DefaultClient, Attempts: 3, Backoff: time.Millisecond}
}

func TestForwarderRetriesServerErrorsThenSucceeds(t *testing.T) {
	var calls atomic.Int32
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Ingest-Token") != "secret" {
			t.Errorf("missing token")
		}
		if calls.Add(1) < 3 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.WriteHeader(http.StatusCreated)
	}))
	defer api.Close()
	s, _ := Summarize(flight(5))
	status, err := newForwarder(api.URL).Send(context.Background(), s)
	if err != nil || status != http.StatusCreated || calls.Load() != 3 {
		t.Fatalf("status=%d err=%v calls=%d", status, err, calls.Load())
	}
}

func TestForwarderDoesNotRetryValidationErrors(t *testing.T) {
	var calls atomic.Int32
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusBadRequest)
		_, _ = io.WriteString(w, `{"code":"unknown_aircraft"}`)
	}))
	defer api.Close()
	s, _ := Summarize(flight(5))
	_, err := newForwarder(api.URL).Send(context.Background(), s)
	var perm *PermanentError
	if !errors.As(err, &perm) || calls.Load() != 1 {
		t.Fatalf("err=%v calls=%d", err, calls.Load())
	}
}

func TestHandlerEndToEnd(t *testing.T) {
	var got FlightSummary
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewDecoder(r.Body).Decode(&got)
		w.WriteHeader(http.StatusCreated)
	}))
	defer api.Close()
	srv := httptest.NewServer(newMux(newForwarder(api.URL), slog.New(slog.NewTextHandler(io.Discard, nil))))
	defer srv.Close()

	body, _ := json.Marshal(flight(30))
	res, err := http.Post(srv.URL+"/v1/telemetry", "application/json", strings.NewReader(string(body)))
	if err != nil {
		t.Fatal(err)
	}
	if res.StatusCode != http.StatusAccepted || got.ExternalID != "GS-1" || got.TailNumber != "TB2-T001" {
		t.Fatalf("status=%d forwarded=%+v", res.StatusCode, got)
	}

	res, _ = http.Post(srv.URL+"/v1/telemetry", "application/json", strings.NewReader(`{"bogus": 1}`))
	if res.StatusCode != http.StatusBadRequest {
		t.Fatalf("unknown fields should be rejected, got %d", res.StatusCode)
	}
}
