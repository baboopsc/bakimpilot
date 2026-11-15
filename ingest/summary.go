package main

import (
	"errors"
	"fmt"
	"math"
	"time"
)

// Sample is one telemetry reading from the ground control station (typically 1 Hz).
type Sample struct {
	T           time.Time `json:"t"`
	OnGround    bool      `json:"on_ground"`
	EngineTempC float64   `json:"engine_temp_c"`
	VibrationG  float64   `json:"vibration_g"`
	FuelFlowLPH float64   `json:"fuel_flow_lph"` // litres per hour
}

// Telemetry is one flight's raw data as uploaded after landing.
type Telemetry struct {
	FlightID   string   `json:"flight_id"`
	TailNumber string   `json:"tail_number"`
	Mission    string   `json:"mission"`
	Samples    []Sample `json:"samples"`
}

// FlightSummary is what BakımPilot stores: thousands of samples reduced to a
// few numbers. Field names match the Django ingest endpoint.
type FlightSummary struct {
	ExternalID     string    `json:"external_id"`
	TailNumber     string    `json:"tail_number"`
	TakeoffAt      time.Time `json:"takeoff_at"`
	LandingAt      time.Time `json:"landing_at"`
	Cycles         int       `json:"cycles"`
	MaxEngineTempC float64   `json:"max_engine_temp_c"`
	AvgVibrationG  float64   `json:"avg_vibration_g"`
	FuelUsedL      float64   `json:"fuel_used_l"`
	Mission        string    `json:"mission"`
}

var (
	ErrNoSamples   = errors.New("no samples")
	ErrNotAirborne = errors.New("aircraft never left the ground")
	ErrTimeOrder   = errors.New("samples are not in time order")
)

// A gap longer than this means missing data, not flight time.
const maxGap = 5 * time.Minute

// Summarize reduces raw telemetry to a flight summary.
//
//   - take-off / landing: first and last airborne sample
//   - cycles: number of ground-to-air transitions (a touch-and-go counts)
//   - vibration: mean over airborne samples; temperature: maximum
//   - fuel: integral of fuel flow over time (trapezoid rule), skipping gaps > maxGap
func Summarize(t Telemetry) (FlightSummary, error) {
	if t.FlightID == "" || t.TailNumber == "" {
		return FlightSummary{}, errors.New("flight_id and tail_number are required")
	}
	if len(t.Samples) == 0 {
		return FlightSummary{}, ErrNoSamples
	}
	s := FlightSummary{ExternalID: t.FlightID, TailNumber: t.TailNumber, Mission: t.Mission}
	var (
		vibSum   float64
		airborne int
		wasAir   bool
		fuel     float64
	)
	s.MaxEngineTempC = math.Inf(-1)
	for i, x := range t.Samples {
		if i > 0 {
			prev := t.Samples[i-1]
			dt := x.T.Sub(prev.T)
			if dt < 0 {
				return FlightSummary{}, fmt.Errorf("%w at sample %d", ErrTimeOrder, i)
			}
			if dt <= maxGap {
				fuel += (prev.FuelFlowLPH + x.FuelFlowLPH) / 2 * dt.Hours()
			}
		}
		s.MaxEngineTempC = math.Max(s.MaxEngineTempC, x.EngineTempC)
		if !x.OnGround {
			if airborne == 0 {
				s.TakeoffAt = x.T
			}
			if !wasAir {
				s.Cycles++
			}
			s.LandingAt = x.T
			vibSum += x.VibrationG
			airborne++
		}
		wasAir = !x.OnGround
	}
	if airborne == 0 {
		return FlightSummary{}, ErrNotAirborne
	}
	if !s.LandingAt.After(s.TakeoffAt) {
		return FlightSummary{}, errors.New("flight too short to log")
	}
	s.AvgVibrationG = round(vibSum/float64(airborne), 3)
	s.MaxEngineTempC = round(s.MaxEngineTempC, 1)
	s.FuelUsedL = round(fuel, 2)
	return s, nil
}

func round(v float64, places int) float64 {
	p := math.Pow(10, float64(places))
	return math.Round(v*p) / p
}
