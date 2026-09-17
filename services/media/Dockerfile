# Use the official Golang image as a base
FROM golang:1.20-alpine

# Set the working directory
WORKDIR /app

# Copy go.mod and go.sum files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy the source code
COPY . .

# Build the application
RUN go build -o media-gateway ./cmd/media

# Expose the port the app runs on
EXPOSE 8080

# Command to run the executable
CMD ["./media-gateway"]
