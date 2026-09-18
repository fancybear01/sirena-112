package domain_test

import (
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

func TestCallTransitions(t *testing.T) {
	c := &domain.Call{State: domain.CallStateNew}
	if err := c.Transition(domain.CallStateRinging); err != nil {
		t.Fatal(err)
	}
	if err := c.Transition(domain.CallStateActive); err != nil {
		t.Fatal(err)
	}
	if err := c.Transition(domain.CallStateEnding); err != nil {
		t.Fatal(err)
	}
	if err := c.Transition(domain.CallStateEnded); err != nil {
		t.Fatal(err)
	}
	if err := c.Transition(domain.CallStateActive); err == nil {
		t.Fatal("expected invalid transition from ENDED")
	}
}

func TestPCMFrameSize(t *testing.T) {
	if domain.PCMFrameBytes != 640 {
		t.Fatalf("expected 640, got %d", domain.PCMFrameBytes)
	}
}
