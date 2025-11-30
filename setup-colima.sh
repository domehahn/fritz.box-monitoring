#!/bin/bash

################################################################################
# Colima Docker Engine Setup Script
# Automates the startup and configuration of Colima for Fritz!Box Monitoring
# Usage: ./setup-colima.sh [--help] [--verbose]
################################################################################

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COLIMA_PROFILE="fritz-monitoring"
COLIMA_CPU="${COLIMA_CPU:-4}"
COLIMA_MEMORY="${COLIMA_MEMORY:-6}"
COLIMA_DISK="${COLIMA_DISK:-50}"
VERBOSE=${VERBOSE:-false}

# Functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_section() {
    echo ""
    echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

verbose_log() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo "[DEBUG] $1"
    fi
}

print_help() {
    cat << EOF
${BLUE}Colima Docker Engine Setup for Fritz!Box Monitoring${NC}

Usage: ./setup-colima.sh [OPTIONS]

Options:
    -h, --help          Show this help message
    -v, --verbose       Enable verbose logging
    --cpu <num>         Number of CPU cores (default: 4)
    --memory <num>      Memory in GB (default: 6)
    --disk <num>        Disk size in GB (default: 50)

Examples:
    ./setup-colima.sh                          # Default setup
    ./setup-colima.sh --verbose                # With debug output
    ./setup-colima.sh --cpu 6 --memory 8       # Custom resources
    ./setup-colima.sh --help                   # Show this help

Environment Variables:
    COLIMA_CPU          Override CPU count
    COLIMA_MEMORY       Override memory (GB)
    COLIMA_DISK         Override disk size (GB)
    VERBOSE             Set to 'true' for verbose output

EOF
}

check_colima_installed() {
    log_section "Checking Prerequisites"

    if ! command -v colima &> /dev/null; then
        log_error "Colima is not installed!"
        echo ""
        log_info "Install Colima using Homebrew:"
        echo "  brew install colima"
        echo ""
        log_info "Or download from: https://github.com/abiosoft/colima"
        exit 1
    fi
    log_success "Colima is installed"
    verbose_log "Colima version: $(colima version 2>/dev/null || echo 'unknown')"

    if ! command -v docker &> /dev/null; then
        log_warning "Docker CLI not found in PATH"
        log_info "It will be available after Colima starts"
    else
        log_success "Docker CLI is available"
    fi
}

check_colima_running() {
    verbose_log "Checking if Colima is already running..."
    if colima status "$COLIMA_PROFILE" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

start_colima() {
    log_section "Starting Colima"

    if check_colima_running; then
        log_warning "Colima profile '$COLIMA_PROFILE' is already running"
        log_info "Skipping start..."
        return 0
    fi

    log_info "Starting Colima with:"
    echo "  • Profile: $COLIMA_PROFILE"
    echo "  • CPU: $COLIMA_CPU cores"
    echo "  • Memory: ${COLIMA_MEMORY}GB"
    echo "  • Disk: ${COLIMA_DISK}GB"
    echo ""

    if [[ "$VERBOSE" == "true" ]]; then
        colima start "$COLIMA_PROFILE" \
            --cpu "$COLIMA_CPU" \
            --memory "$COLIMA_MEMORY" \
            --disk "$COLIMA_DISK" \
            --network-address || {
            log_error "Failed to start Colima"
            exit 1
        }
    else
        colima start "$COLIMA_PROFILE" \
            --cpu "$COLIMA_CPU" \
            --memory "$COLIMA_MEMORY" \
            --disk "$COLIMA_DISK" \
            --network-address &> /dev/null || {
            log_error "Failed to start Colima"
            exit 1
        }
    fi

    log_success "Colima started successfully"
}

verify_docker() {
    log_section "Verifying Docker"

    # Wait for Docker daemon to be ready
    max_attempts=30
    attempt=1

    while [ $attempt -le $max_attempts ]; do
        if docker info &> /dev/null; then
            log_success "Docker daemon is responsive"
            return 0
        fi

        if [ $attempt -eq 1 ]; then
            log_info "Waiting for Docker daemon to be ready..."
        fi

        echo -n "."
        sleep 1
        ((attempt++))
    done

    echo ""
    log_error "Docker daemon failed to become responsive"
    exit 1
}

test_docker() {
    log_section "Testing Docker"

    log_info "Pulling and running test image..."
    if docker run --rm hello-world &> /dev/null; then
        log_success "Docker is working correctly"
    else
        log_error "Docker test failed"
        exit 1
    fi
}

show_docker_info() {
    log_section "Docker Information"

    echo "Docker Version:"
    docker version --format '  • Client: {{.Client.Version}}{{"\n"}}  • Server: {{.Server.Version}}'

    echo ""
    echo "Docker System Info:"
    docker system df | head -5

    echo ""
    echo "Docker Daemon Status:"
    docker info 2>/dev/null | grep -E "Architecture|OS|CPUs|MemTotal" | sed 's/^/  • /'

    echo ""
    echo "Available Networks:"
    docker network ls | tail -n +2 | head -5 | sed 's/^/  • /'
}

setup_docker_compose() {
    log_section "Docker Compose Setup"

    if ! command -v docker-compose &> /dev/null; then
        if ! docker compose version &> /dev/null; then
            log_warning "Docker Compose is not available"
            log_info "Installing via Docker (compose plugin)..."
            # Usually already included with Docker Desktop/Colima
            log_warning "Skipping - ensure Docker Compose is installed"
            return 1
        fi
    fi

    log_success "Docker Compose is available"
    docker compose version | sed 's/^/  • /'
}

show_next_steps() {
    log_section "Next Steps"

    echo "1. Configure Fritz!Box credentials:"
    echo "   ${BLUE}cp .env.example .env${NC}"
    echo "   Edit .env with your Fritz!Box credentials"
    echo ""

    echo "2. Start the monitoring stack:"
    echo "   ${BLUE}docker-compose up -d${NC}"
    echo "   or: ${BLUE}make start${NC}"
    echo ""

    echo "3. Access the services:"
    echo "   • Grafana:      ${BLUE}http://localhost:3000${NC} (admin/admin)"
    echo "   • Prometheus:   ${BLUE}http://localhost:9090${NC}"
    echo "   • Exporter:     ${BLUE}http://localhost:8000/metrics${NC}"
    echo ""

    echo "4. Check logs:"
    echo "   ${BLUE}docker-compose logs -f fritz_exporter${NC}"
    echo "   or: ${BLUE}make logs${NC}"
    echo ""

    echo "5. Useful commands:"
    echo "   • Stop Colima:        ${BLUE}colima stop${NC}"
    echo "   • Remove Colima:      ${BLUE}colima delete${NC}"
    echo "   • Docker stats:       ${BLUE}docker stats${NC}"
    echo "   • List containers:    ${BLUE}docker ps${NC}"
    echo ""
}

show_colima_tips() {
    log_section "Colima Tips & Tricks"

    echo "Resource Limits:"
    echo "  • Adjust CPU/Memory: colima start --cpu 6 --memory 8"
    echo "  • Check current settings: colima status"
    echo ""

    echo "Networking:"
    echo "  • Colima provides network-address for VM-to-host communication"
    echo "  • Use 'localhost' for access from macOS"
    echo ""

    echo "Troubleshooting:"
    echo "  • Check status:       ${BLUE}colima status${NC}"
    echo "  • View logs:          ${BLUE}colima logs${NC}"
    echo "  • Restart:            ${BLUE}colima restart${NC}"
    echo "  • Full reset:         ${BLUE}colima delete && colima start${NC}"
    echo ""

    echo "Performance Tips:"
    echo "  • Stop when not in use: colima stop"
    echo "  • Monitor usage: colima status"
    echo "  • Increase disk if needed: colima delete && colima start --disk 100"
    echo ""
}

cleanup_on_error() {
    log_error "Setup failed!"
    echo ""
    log_info "To troubleshoot:"
    echo "  1. Check Colima status: colima status"
    echo "  2. View logs: colima logs"
    echo "  3. Test docker: docker ps"
    echo "  4. Run with verbose: VERBOSE=true ./setup-colima.sh"
}

# Main execution
main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                print_help
                exit 0
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            --cpu)
                COLIMA_CPU="$2"
                shift 2
                ;;
            --memory)
                COLIMA_MEMORY="$2"
                shift 2
                ;;
            --disk)
                COLIMA_DISK="$2"
                shift 2
                ;;
            *)
                log_error "Unknown option: $1"
                echo ""
                print_help
                exit 1
                ;;
        esac
    done

    # Set up error handling
    trap cleanup_on_error EXIT

    # Run setup steps
    log_section "Colima Setup for Fritz!Box Monitoring"

    check_colima_installed
    start_colima
    verify_docker
    test_docker
    show_docker_info
    setup_docker_compose

    # Remove error trap on success
    trap - EXIT

    show_next_steps
    show_colima_tips

    log_section "✓ Setup Complete!"
    echo ""
    log_success "Colima is ready for Fritz!Box Monitoring!"
    echo ""
}

# Run main function
main "$@"
