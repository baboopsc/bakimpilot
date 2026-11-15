package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Forwarder sends summaries to the BakımPilot API.
//
// Retries are safe because the API is idempotent on external_id: a summary
// that was stored but whose response got lost is simply acknowledged again.
type Forwarder struct {
	URL      string // e.g. http://api:8000/api/ingest/flights/
	Token    string
	Client   *http.Client
	Attempts int
	Backoff  time.Duration
}

// PermanentError means retrying cannot help (validation error, bad token...).
type PermanentError struct {
	Status int
	Body   string
}

func (e *PermanentError) Error() string {
	return fmt.Sprintf("api rejected flight: %d %s", e.Status, e.Body)
}

// Send posts the summary, retrying network errors, 5xx and 429 with exponential backoff.
func (f *Forwarder) Send(ctx context.Context, s FlightSummary) (int, error) {
	body, err := json.Marshal(s)
	if err != nil {
		return 0, err
	}
	wait := f.Backoff
	var status int
	for attempt := 1; attempt <= f.Attempts; attempt++ {
		status, err = f.once(ctx, body)
		var perm *PermanentError
		if err == nil || errors.As(err, &perm) || attempt == f.Attempts {
			return status, err
		}
		select {
		case <-time.After(wait):
			wait *= 2
		case <-ctx.Done():
			return 0, ctx.Err()
		}
	}
	return status, err
}

func (f *Forwarder) once(ctx context.Context, body []byte) (int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, f.URL, bytes.NewReader(body))
	if err != nil {
		return 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Ingest-Token", f.Token)
	res, err := f.Client.Do(req)
	if err != nil {
		return 0, err // network error: retry
	}
	defer res.Body.Close()
	msg, _ := io.ReadAll(io.LimitReader(res.Body, 2048))
	switch {
	case res.StatusCode == http.StatusOK || res.StatusCode == http.StatusCreated:
		return res.StatusCode, nil
	case res.StatusCode >= 500 || res.StatusCode == http.StatusTooManyRequests:
		return res.StatusCode, fmt.Errorf("api temporarily unavailable: %d", res.StatusCode)
	default:
		return res.StatusCode, &PermanentError{Status: res.StatusCode, Body: string(msg)}
	}
}
