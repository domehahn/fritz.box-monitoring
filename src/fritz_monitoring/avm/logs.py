"""Fritz!Box log collection and parsing."""

import re
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class LogEntry:
    """Represents a single Fritz!Box log entry."""
    timestamp: datetime
    raw_timestamp: str
    message: str
    source: Optional[str] = None  # e.g., [fritz.repeater], [EG]
    severity: str = "info"
    category: Optional[str] = None


class FritzLogParser:
    """Parse Fritz!Box log entries."""
    
    # Log patterns
    LOG_PATTERN = re.compile(
        r'^(\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})\s+'  # timestamp
        r'(?:\[([^\]]+)\]\s+)?'  # optional source in brackets
        r'(.+)$'  # message
    )
    
    # Severity keywords
    SEVERITY_ERROR = ['fehler', 'error', 'failed', 'fehlgeschlagen']
    SEVERITY_WARNING = ['warnung', 'warning', 'reduziert', 'getrennt', 'unterbrochen']
    SEVERITY_INFO = ['erfolgreich', 'success', 'hergestellt', 'bezogen']
    
    # Category patterns
    CATEGORIES = {
        'internet': ['internet', 'ipv6', 'dns', 'pppoe', 'gateway'],
        'wlan': ['wlan', 'wifi', 'kanal', 'channel', 'frequenz'],
        'connection': ['verbindung', 'connection', 'anmeldung', 'login'],
        'device': ['gerät', 'device', 'repeater', 'powerline'],
        'system': ['system', 'neustart', 'reboot', 'update'],
    }
    
    def parse_log_line(self, line: str) -> Optional[LogEntry]:
        """Parse a single log line."""
        if not line.strip():
            return None
            
        match = self.LOG_PATTERN.match(line)
        if not match:
            return None
            
        raw_timestamp, source, message = match.groups()
        
        # Parse timestamp (format: DD.MM.YY HH:MM:SS)
        try:
            timestamp = datetime.strptime(raw_timestamp, '%d.%m.%y %H:%M:%S')
        except ValueError:
            return None
        
        # Determine severity
        message_lower = message.lower()
        severity = 'info'
        for keyword in self.SEVERITY_ERROR:
            if keyword in message_lower:
                severity = 'error'
                break
        if severity == 'info':
            for keyword in self.SEVERITY_WARNING:
                if keyword in message_lower:
                    severity = 'warning'
                    break
        
        # Determine category
        category = None
        for cat_name, keywords in self.CATEGORIES.items():
            for keyword in keywords:
                if keyword in message_lower:
                    category = cat_name
                    break
            if category:
                break
        
        return LogEntry(
            timestamp=timestamp,
            raw_timestamp=raw_timestamp,
            message=message.strip(),
            source=source,
            severity=severity,
            category=category
        )
    
    def parse_logs(self, log_text: str) -> List[LogEntry]:
        """Parse multiple log lines."""
        entries = []
        for line in log_text.split('\n'):
            entry = self.parse_log_line(line)
            if entry:
                entries.append(entry)
        return entries


class FritzLogCollector:
    """Collect logs from Fritz!Box."""
    
    def __init__(self, client):
        """Initialize log collector with Fritz client."""
        self.client = client
        self.parser = FritzLogParser()
    
    def get_logs(self) -> List[LogEntry]:
        """Fetch and parse logs from Fritz!Box."""
        try:
            result = self.client.fc.call_action('DeviceInfo1', 'GetDeviceLog')
            log_text = result.get('NewDeviceLog', '')
            return self.parser.parse_logs(log_text)
        except Exception as e:
            print(f"Error fetching logs: {e}")
            return []
    
    def get_log_stats(self) -> Dict[str, int]:
        """Get statistics about logs."""
        logs = self.get_logs()
        
        stats = {
            'total': len(logs),
            'error': 0,
            'warning': 0,
            'info': 0,
        }
        
        # Count by severity
        for log in logs:
            stats[log.severity] = stats.get(log.severity, 0) + 1
        
        # Count by category
        categories = {}
        for log in logs:
            if log.category:
                categories[log.category] = categories.get(log.category, 0) + 1
        
        stats['by_category'] = categories
        
        # Count by source
        sources = {}
        for log in logs:
            if log.source:
                sources[log.source] = sources.get(log.source, 0) + 1
        
        stats['by_source'] = sources
        
        return stats
