package domain

import "errors"

var (
	ErrInvalidTransition = errors.New("invalid call state transition")
	ErrCallNotFound      = errors.New("call not found")
	ErrCallExists        = errors.New("call already exists for session")
	ErrInvalidArgument   = errors.New("invalid argument")
	ErrARIUnavailable    = errors.New("ari unavailable")
	ErrCapacityExhausted = errors.New("media call capacity exhausted")
	ErrNotImplemented    = errors.New("not implemented")
)
