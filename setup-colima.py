#!/usr/bin/env python3

"""
Colima Setup Script for Fritz!Box Monitoring (Platform-Independent)

This script provides a Python-based alternative to the bash script,
useful for cross-platform compatibility.

Usage:
    python3 setup-colima.py [--help] [--verbose]
    python3 setup-colima.py --cpu 6 --memory 8 --disk 100
"""

import subprocess
import sys
import time
import argparse
from pathlib import Path
from typing import Optional, Tuple


class Colors:
    """ANSI color codes"""
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    RESET = '\033[0m'

    @staticmethod
    def disable():
        """Disable colors (for non-TTY output)"""
        Colors.BLUE = ''
        Colors.GREEN = ''
        Colors.YELLOW = ''
        Colors.RED = ''
        Colors.RESET = ''


def log_info(msg: str):
    """Log info message"""
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {msg}")


def log_success(msg: str):
    """Log success message"""
    print(f"{Colors.GREEN}✓{Colors.RESET} {msg}")


def log_warning(msg: str):
    """Log warning message"""
    print(f"{Colors.YELLOW}⚠{Colors.RESET} {msg}")


def log_error(msg: str):
    """Log error message"""
    print(f"{Colors.RED}✗{Colors.RESET} {msg}")


def log_section(title: str):
    """Log section header"""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}  {title}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}\n")


def run_command(cmd: list, check: bool = True, capture: bool = False, verbose: bool = False) -> Tuple[int, str]:
    """Run a shell command"""
    try:
        if verbose:
            print(f"[DEBUG] Running: {' '.join(cmd)}")

        if capture:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return result.returncode, result.stdout.strip()
        else:
            result = subprocess.run(cmd, check=check)
            return result.returncode, ""
    except subprocess.CalledProcessError as e:
        if check:
            raise
        return e.returncode, ""
    except FileNotFoundError:
        log_error(f"Command not found: {cmd[0]}")
        return 1, ""


def command_exists(cmd: str) -> bool:
    """Check if command exists"""
    result = subprocess.run(['which', cmd], capture_output=True)
    return result.returncode == 0


def check_colima_installed(verbose: bool = False):
    """Check if Colima is installed"""
    log_section("Checking Prerequisites")

    if not command_exists('colima'):
        log_error("Colima is not installed!")
        print()
        log_info("Install Colima using Homebrew:")
        print("  brew install colima")
        print()
        log_info("Or download from: https://github.com/abiosoft/colima")
        sys.exit(1)

    log_success("Colima is installed")

    if command_exists('docker'):
        log_success("Docker CLI is available")
    else:
        log_warning("Docker CLI not found in PATH - will be available after Colima starts")


def check_colima_running(profile: str, verbose: bool = False) -> bool:
    """Check if Colima is running"""
    returncode, _ = run_command(['colima', 'status', profile], check=False, verbose=verbose)
    return returncode == 0


def start_colima(profile: str, cpu: int, memory: int, disk: int, verbose: bool = False):
    """Start Colima"""
    log_section("Starting Colima")

    if check_colima_running(profile, verbose):
        log_warning(f"Colima profile '{profile}' is already running")
        log_info("Skipping start...")
        return

    log_info("Starting Colima with:")
    print(f"  • Profile: {profile}")
    print(f"  • CPU: {cpu} cores")
    print(f"  • Memory: {memory}GB")
    print(f"  • Disk: {disk}GB")
    print()

    cmd = ['colima', 'start', profile,
           '--cpu', str(cpu),
           '--memory', str(memory),
           '--disk', str(disk),
           '--network-address']

    returncode, _ = run_command(cmd, check=False, verbose=verbose)

    if returncode != 0:
        log_error("Failed to start Colima")
        sys.exit(1)

    log_success("Colima started successfully")


def verify_docker(verbose: bool = False):
    """Verify Docker is responsive"""
    log_section("Verifying Docker")

    max_attempts = 30
    attempt = 1

    while attempt <= max_attempts:
        returncode, _ = run_command(['docker', 'info'], check=False, verbose=verbose)
        if returncode == 0:
            log_success("Docker daemon is responsive")
            return

        if attempt == 1:
            log_info("Waiting for Docker daemon to be ready...")

        sys.stdout.write('.')
        sys.stdout.flush()
        time.sleep(1)
        attempt += 1

    print()
    log_error("Docker daemon failed to become responsive")
    sys.exit(1)


def test_docker(verbose: bool = False):
    """Test Docker functionality"""
    log_section("Testing Docker")

    log_info("Pulling and running test image...")
    returncode, _ = run_command(['docker', 'run', '--rm', 'hello-world'],
                                check=False, verbose=verbose)

    if returncode == 0:
        log_success("Docker is working correctly")
    else:
        log_error("Docker test failed")
        sys.exit(1)


def show_docker_info(verbose: bool = False):
    """Show Docker information"""
    log_section("Docker Information")

    print("Docker Version:")
    run_command(['docker', 'version', '--format', '  • Client: {{.Client.Version}}\n  • Server: {{.Server.Version}}'],
                check=False, verbose=verbose)

    print("\nDocker Daemon Status:")
    returncode, output = run_command(['docker', 'info'], capture=True, check=False, verbose=verbose)
    if returncode == 0:
        for line in output.split('\n'):
            if any(x in line for x in ['Architecture', 'OS', 'CPUs', 'MemTotal']):
                print(f"  • {line.strip()}")


def show_next_steps():
    """Show next steps"""
    log_section("Next Steps")

    print("1. Configure Fritz!Box credentials:")
    print(f"   {Colors.BLUE}cp .env.example .env{Colors.RESET}")
    print("   Edit .env with your Fritz!Box credentials")
    print()

    print("2. Start the monitoring stack:")
    print(f"   {Colors.BLUE}docker-compose up -d{Colors.RESET}")
    print(f"   or: {Colors.BLUE}make start{Colors.RESET}")
    print()

    print("3. Access the services:")
    print(f"   • Grafana:      {Colors.BLUE}http://localhost:3000{Colors.RESET} (admin/admin)")
    print(f"   • Prometheus:   {Colors.BLUE}http://localhost:9090{Colors.RESET}")
    print(f"   • Exporter:     {Colors.BLUE}http://localhost:8000/metrics{Colors.RESET}")
    print()

    print("4. Check logs:")
    print(f"   {Colors.BLUE}docker-compose logs -f fritz_exporter{Colors.RESET}")
    print(f"   or: {Colors.BLUE}make logs{Colors.RESET}")
    print()


def show_colima_tips():
    """Show Colima tips"""
    log_section("Colima Tips & Tricks")

    print("Resource Limits:")
    print("  • Adjust CPU/Memory: colima start --cpu 6 --memory 8")
    print("  • Check current settings: colima status")
    print()

    print("Troubleshooting:")
    print(f"  • Check status:       {Colors.BLUE}colima status{Colors.RESET}")
    print(f"  • View logs:          {Colors.BLUE}colima logs{Colors.RESET}")
    print(f"  • Restart:            {Colors.BLUE}colima restart{Colors.RESET}")
    print(f"  • Full reset:         {Colors.BLUE}colima delete && colima start{Colors.RESET}")
    print()


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='Colima Docker Engine Setup for Fritz!Box Monitoring',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 setup-colima.py                      # Default setup
  python3 setup-colima.py --verbose            # With debug output
  python3 setup-colima.py --cpu 6 --memory 8   # Custom resources
        """
    )

    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--cpu', type=int, default=4,
                        help='Number of CPU cores (default: 4)')
    parser.add_argument('--memory', type=int, default=6,
                        help='Memory in GB (default: 6)')
    parser.add_argument('--disk', type=int, default=50,
                        help='Disk size in GB (default: 50)')
    parser.add_argument('--profile', default='fritz-monitoring',
                        help='Colima profile name (default: fritz-monitoring)')

    args = parser.parse_args()

    # Disable colors if not TTY
    if not sys.stdout.isatty():
        Colors.disable()

    try:
        # Run setup steps
        log_section("Colima Setup for Fritz!Box Monitoring")

        check_colima_installed(args.verbose)
        start_colima(args.profile, args.cpu, args.memory, args.disk, args.verbose)
        verify_docker(args.verbose)
        test_docker(args.verbose)
        show_docker_info(args.verbose)

        show_next_steps()
        show_colima_tips()

        log_section("✓ Setup Complete!")
        print()
        log_success("Colima is ready for Fritz!Box Monitoring!")
        print()

    except KeyboardInterrupt:
        print()
        log_warning("Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Setup failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
