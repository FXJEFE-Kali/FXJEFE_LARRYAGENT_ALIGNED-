#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — SECURITY COMMAND CENTER v1.0                      ║
║   Unified interface for ALL security tools                          ║
║   Ties together: port_investigator, network_hunter, traffic_analyzer║
║   vps_security_tester, autonomous_security_toolkit, sentinel        ║
╚══════════════════════════════════════════════════════════════════════╝

Provides:
  - Single CLI entry point for all security operations
  - /security commands for agent_v2.py integration
  - Dashboard API endpoints for dashboard_hub.py
  - Robin (sentinel) integration for automated alerts
  - Minimal resource usage — lazy-loads modules on demand

Usage:
  python security_command_center.py                    # Interactive menu
  python security_command_center.py investigate        # Port investigation
  python security_command_center.py hunt               # Network discovery
  python security_command_center.py traffic            # Traffic analysis
  python security_command_center.py firewall           # Firewall test
  python security_command_center.py full-audit         # Everything
  python security_command_center.py quick              # Fast overview
"""

import json
import time
import logging
import sys
import socket
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

import psutil

# ── Config ────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
REPORTS_DIR = SCRIPT_DIR / "security_reports"
REPORTS_DIR.mkdir(exist_ok=True)
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SEC-CMD] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "security_cmd.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── Lazy Module Loader ────────────────────────────────────────────
# Only imports modules when needed — saves RAM & startup time

class _LazyModules:
    """Lazy-load security modules on first access."""

    _cache = {}

    @classmethod
    def port_investigator(cls):
        if "pi" not in cls._cache:
            try:
                from port_investigator import (
                    investigate_connections,
                    investigate_port,
                    format_investigation_report,
                    format_telegram_report,
                    geolocate_ips,
                    reverse_dns,
                )
                cls._cache["pi"] = {
                    "investigate_connections": investigate_connections,
                    "investigate_port": investigate_port,
                    "format_report": format_investigation_report,
                    "format_telegram": format_telegram_report,
                    "geolocate": geolocate_ips,
                    "rdns": reverse_dns,
                }
            except ImportError as e:
                log.warning(f"port_investigator not available: {e}")
                cls._cache["pi"] = None
        return cls._cache["pi"]

    @classmethod
    def network_hunter(cls):
        if "nh" not in cls._cache:
            try:
                from network_hunter_tools import NetworkHunter, NetworkTarget
                cls._cache["nh"] = {
                    "Hunter": NetworkHunter,
                    "Target": NetworkTarget,
                }
            except ImportError as e:
                log.warning(f"network_hunter_tools not available: {e}")
                cls._cache["nh"] = None
        return cls._cache["nh"]

    @classmethod
    def traffic_analyzer(cls):
        if "ta" not in cls._cache:
            try:
                from traffic_analyzer import TrafficAnalyzer
                cls._cache["ta"] = {"Analyzer": TrafficAnalyzer}
            except ImportError as e:
                log.warning(f"traffic_analyzer not available: {e}")
                cls._cache["ta"] = None
        return cls._cache["ta"]

    @classmethod
    def vps_tester(cls):
        if "vps" not in cls._cache:
            try:
                from vps_security_tester import VPSSecurityTester
                cls._cache["vps"] = {"Tester": VPSSecurityTester}
            except ImportError as e:
                log.warning(f"vps_security_tester not available: {e}")
                cls._cache["vps"] = None
        return cls._cache["vps"]

    @classmethod
    def security_toolkit(cls):
        if "ast" not in cls._cache:
            try:
                from autonomous_security_toolkit import AutonomousSecurityToolkit
                cls._cache["ast"] = {"Toolkit": AutonomousSecurityToolkit}
            except ImportError as e:
                log.warning(f"autonomous_security_toolkit not available: {e}")
                cls._cache["ast"] = None
        return cls._cache["ast"]

    @classmethod
    def web_extractor(cls):
        if "we" not in cls._cache:
            try:
                from web_knowledge_extractor import WebKnowledgeExtractor
                cls._cache["we"] = {"Extractor": WebKnowledgeExtractor}
            except ImportError as e:
                log.warning(f"web_knowledge_extractor not available: {e}")
                cls._cache["we"] = None
        return cls._cache["we"]

    @classmethod
    def bash_runner(cls):
        if "br" not in cls._cache:
            try:
                from bash_script_runner import BashScriptRunner
                cls._cache["br"] = BashScriptRunner()
            except ImportError as e:
                log.warning(f"bash_script_runner not available: {e}")
                cls._cache["br"] = None
        return cls._cache["br"]

Lazy = _LazyModules


# ══════════════════════════════════════════════════════════════════
#  SECURITY COMMAND CENTER
# ══════════════════════════════════════════════════════════════════

class SecurityCommandCenter:
    """
    Unified security operations center for Larry G-Force.
    Orchestrates all security modules through a single interface.
    """

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or str(REPORTS_DIR)
        self.last_results: Dict[str, Any] = {}
        self.scan_history: List[Dict] = []
        Path(self.output_dir).mkdir(exist_ok=True)

    # ── Available Modules Check ───────────────────────────────────

    def check_modules(self) -> Dict[str, bool]:
        """Check which security modules are available."""
        modules = {
            "port_investigator": Lazy.port_investigator() is not None,
            "network_hunter": Lazy.network_hunter() is not None,
            "traffic_analyzer": Lazy.traffic_analyzer() is not None,
            "vps_security_tester": Lazy.vps_tester() is not None,
            "autonomous_toolkit": Lazy.security_toolkit() is not None,
            "web_extractor": Lazy.web_extractor() is not None,
            "bash_runner": Lazy.bash_runner() is not None,
        }
        # Always available (stdlib + psutil)
        modules["system_baseline"] = True
        return modules

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: QUICK OVERVIEW (fast, ~2 seconds)
    # ══════════════════════════════════════════════════════════════

    def quick_overview(self) -> Dict[str, Any]:
        """
        Fast system security snapshot. No external API calls.
        Use this for the /security or /quick command.
        """
        start = time.time()
        result = {
            "timestamp": datetime.now().isoformat(),
            "type": "quick_overview",
        }

        # ── System resources ──
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        result["system"] = {
            "cpu_pct": cpu,
            "mem_pct": mem.percent,
            "mem_used_gb": round(mem.used / 1e9, 1),
            "mem_total_gb": round(mem.total / 1e9, 1),
            "disk_pct": disk.percent,
        }

        # ── Network connections summary ──
        conns = psutil.net_connections(kind="inet")
        listening = [c for c in conns if c.status == "LISTEN"]
        established = [c for c in conns if c.status == "ESTABLISHED"]
        unique_remote = set()
        by_process = defaultdict(int)
        for c in established:
            if c.raddr:
                unique_remote.add(c.raddr.ip)
            if c.pid:
                try:
                    by_process[psutil.Process(c.pid).name()] += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        result["network"] = {
            "total_connections": len(conns),
            "listening_ports": len(listening),
            "established": len(established),
            "unique_remote_ips": len(unique_remote),
            "top_processes": dict(sorted(by_process.items(), key=lambda x: -x[1])[:10]),
            "listening_port_list": sorted(set(
                c.laddr.port for c in listening if c.laddr
            )),
        }

        # ── VPN status ──
        vpn_up = False
        vpn_iface = None
        for iface in psutil.net_if_addrs().keys():
            if any(x in iface.lower() for x in ["tun", "tap", "wg", "nordlynx", "proton", "mullvad"]):
                stats = psutil.net_if_stats().get(iface)
                if stats and stats.isup:
                    vpn_up = True
                    vpn_iface = iface
                    break
        result["vpn"] = {"active": vpn_up, "interface": vpn_iface}

        # ── Exposed services (bound to 0.0.0.0) ──
        exposed = []
        for c in listening:
            if c.laddr and c.laddr.ip in ("0.0.0.0", "::", ""):
                proc_name = "?"
                if c.pid:
                    try:
                        proc_name = psutil.Process(c.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                exposed.append({"port": c.laddr.port, "process": proc_name})
        result["exposed_services"] = exposed

        # ── Risk assessment ──
        risk = "LOW"
        warnings = []
        if not vpn_up:
            warnings.append("VPN is down")
        if len(exposed) > 10:
            risk = "MEDIUM"
            warnings.append(f"{len(exposed)} services exposed to network")
        if cpu > 90:
            warnings.append(f"CPU critically high: {cpu}%")
        if mem.percent > 92:
            warnings.append(f"Memory critically high: {mem.percent}%")
            risk = "HIGH" if risk != "HIGH" else risk
        result["risk_level"] = risk
        result["warnings"] = warnings
        result["scan_time_sec"] = round(time.time() - start, 2)

        self.last_results["quick"] = result
        return result

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: PORT INVESTIGATION (with geo, ~3-5 seconds)
    # ══════════════════════════════════════════════════════════════

    def investigate_ports(self, port: int = None, no_geo: bool = False,
                          no_dns: bool = False, verbose: bool = True) -> Dict:
        """
        Deep port/connection investigation with geolocation.
        Wraps port_investigator module.
        """
        pi = Lazy.port_investigator()
        if not pi:
            return {"error": "port_investigator.py not found — place it in the Agent-Larry directory"}

        if port:
            data = pi["investigate_port"](port)
        else:
            data = pi["investigate_connections"](
                include_geo=not no_geo,
                include_dns=not no_dns,
            )

        self.last_results["investigate"] = data
        self._save_report("port_investigation", data)
        return data

    def format_investigation(self, data: dict = None, verbose: bool = True) -> str:
        """Format port investigation results for terminal."""
        pi = Lazy.port_investigator()
        if not pi:
            return "port_investigator not available"
        data = data or self.last_results.get("investigate", {})
        return pi["format_report"](data, verbose=verbose)

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: NETWORK HUNT (discovery + services + OS)
    # ══════════════════════════════════════════════════════════════

    def network_hunt(self, network: str = None, ports: List[int] = None,
                     os_fingerprint: bool = True, security_check: bool = True) -> Dict:
        """
        Active network reconnaissance.
        Wraps network_hunter_tools module.
        """
        nh = Lazy.network_hunter()
        if not nh:
            return {"error": "network_hunter_tools.py not found"}

        network = network or self._detect_network()
        hunter = nh["Hunter"](output_dir=self.output_dir)
        target = nh["Target"](
            network_range=network,
            ports_to_scan=ports or [22, 80, 443, 8080, 8081, 5560, 8082, 3306, 5432, 6379, 11434],
        )

        results = {"type": "network_hunt", "network": network, "timestamp": datetime.now().isoformat()}

        # Stage 1: Discover hosts
        discovery = hunter.discover_hosts(target)
        results["discovery"] = discovery

        discovered_ips = [h.get("ip") for h in discovery.get("hosts_found", []) if h.get("ip")]

        if discovered_ips:
            # Stage 2: Service detection
            services = hunter.scan_services(discovered_ips, target.ports_to_scan)
            results["services"] = services

            # Stage 3: OS fingerprinting
            if os_fingerprint:
                fingerprints = hunter.fingerprint_os(discovered_ips)
                results["os_fingerprints"] = fingerprints

            # Stage 4: Security checks
            if security_check:
                security = hunter.check_network_security(discovered_ips)
                results["security_issues"] = security

        self.last_results["hunt"] = results
        self._save_report("network_hunt", results)
        return results

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: TRAFFIC ANALYSIS
    # ══════════════════════════════════════════════════════════════

    def analyze_traffic(self, hosts: List[str] = None, interface: str = None,
                        duration: int = 15, capture: bool = False) -> Dict:
        """
        Network traffic analysis and anomaly detection.
        Wraps traffic_analyzer module.
        """
        ta = Lazy.traffic_analyzer()
        if not ta:
            return {"error": "traffic_analyzer.py not found"}

        hosts = hosts or ["127.0.0.1"]
        analyzer = ta["Analyzer"](output_dir=self.output_dir)

        results = {"type": "traffic_analysis", "timestamp": datetime.now().isoformat()}

        # Interfaces
        results["interfaces"] = analyzer.get_network_interfaces()

        # Traffic capture (only if explicitly requested — needs sudo)
        if capture:
            results["capture"] = analyzer.capture_traffic(interface, duration)

        # Flow analysis
        results["flows"] = analyzer.analyze_flows(hosts)

        # Anomaly detection
        results["anomalies"] = analyzer.detect_anomalies(hosts)

        # Latency monitoring
        results["latency"] = analyzer.monitor_latency(hosts, samples=5)

        self.last_results["traffic"] = results
        self._save_report("traffic_analysis", results)
        return results

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: FIREWALL & VPS TEST
    # ══════════════════════════════════════════════════════════════

    def test_firewall(self, hosts: List[str] = None,
                       vpn_endpoints: List[str] = None) -> Dict:
        """
        Firewall effectiveness and VPN security testing.
        Wraps vps_security_tester module.
        """
        vps = Lazy.vps_tester()
        if not vps:
            return {"error": "vps_security_tester.py not found"}

        hosts = hosts or ["127.0.0.1"]
        tester = vps["Tester"](output_dir=self.output_dir)

        results = {"type": "firewall_test", "timestamp": datetime.now().isoformat()}

        # VPN connectivity (if endpoints provided)
        if vpn_endpoints:
            results["vpn"] = tester.test_vpn_connectivity(vpn_endpoints)

        # Firewall rules
        results["firewall"] = tester.test_firewall_rules(hosts)

        # Encryption tests
        results["encryption"] = tester.test_encryption()

        self.last_results["firewall"] = results
        self._save_report("firewall_test", results)
        return results

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: AUTONOMOUS TOOLKIT (network audit + VM)
    # ══════════════════════════════════════════════════════════════

    def autonomous_audit(self, network: str = None) -> Dict:
        """
        Full autonomous security audit using the toolkit.
        Wraps autonomous_security_toolkit module.
        """
        ast = Lazy.security_toolkit()
        if not ast:
            return {"error": "autonomous_security_toolkit.py not found"}

        toolkit = ast["Toolkit"]()
        audit = toolkit.autonomous_network_audit(network)

        self.last_results["audit"] = audit
        self._save_report("autonomous_audit", audit)
        return audit

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: FULL SECURITY AUDIT (runs everything)
    # ══════════════════════════════════════════════════════════════

    def full_audit(self, network: str = None, hosts: List[str] = None) -> Dict:
        """
        Complete security audit — runs every available module.
        Takes 30-60 seconds depending on network size.
        """
        start = time.time()
        network = network or self._detect_network()
        hosts = hosts or ["127.0.0.1"]

        report = {
            "type": "full_audit",
            "timestamp": datetime.now().isoformat(),
            "network": network,
            "modules_run": [],
            "modules_failed": [],
        }

        # 1. Quick overview (always works)
        log.info("━━━ Stage 1/5: System overview...")
        report["overview"] = self.quick_overview()
        report["modules_run"].append("quick_overview")

        # 2. Port investigation
        log.info("━━━ Stage 2/5: Port investigation...")
        try:
            report["investigation"] = self.investigate_ports()
            report["modules_run"].append("port_investigator")
        except Exception as e:
            report["modules_failed"].append({"module": "port_investigator", "error": str(e)})
            log.warning(f"Port investigation failed: {e}")

        # 3. Network hunt
        log.info("━━━ Stage 3/5: Network reconnaissance...")
        try:
            report["network_hunt"] = self.network_hunt(network)
            report["modules_run"].append("network_hunter")
        except Exception as e:
            report["modules_failed"].append({"module": "network_hunter", "error": str(e)})
            log.warning(f"Network hunt failed: {e}")

        # 4. Traffic analysis
        log.info("━━━ Stage 4/5: Traffic analysis...")
        try:
            report["traffic"] = self.analyze_traffic(hosts)
            report["modules_run"].append("traffic_analyzer")
        except Exception as e:
            report["modules_failed"].append({"module": "traffic_analyzer", "error": str(e)})
            log.warning(f"Traffic analysis failed: {e}")

        # 5. Firewall test
        log.info("━━━ Stage 5/5: Firewall testing...")
        try:
            report["firewall"] = self.test_firewall(hosts)
            report["modules_run"].append("vps_security_tester")
        except Exception as e:
            report["modules_failed"].append({"module": "vps_security_tester", "error": str(e)})
            log.warning(f"Firewall test failed: {e}")

        report["total_time_sec"] = round(time.time() - start, 2)
        report["modules_available"] = len(report["modules_run"])
        report["modules_total"] = 5

        # Aggregate risk level
        risk = "LOW"
        all_warnings = report.get("overview", {}).get("warnings", [])
        hunt_issues = report.get("network_hunt", {}).get("security_issues", {}).get("security_issues", [])
        anomalies = report.get("traffic", {}).get("anomalies", {}).get("anomalies", [])

        if any(i.get("severity") == "high" for i in hunt_issues):
            risk = "HIGH"
        elif anomalies:
            risk = "MEDIUM"
        elif len(all_warnings) > 2:
            risk = "MEDIUM"

        report["overall_risk"] = risk

        self.last_results["full_audit"] = report
        self._save_report("full_audit", report)
        log.info(f"Full audit complete in {report['total_time_sec']}s — Risk: {risk}")
        return report

    # ══════════════════════════════════════════════════════════════
    #  FORMATTED OUTPUT
    # ══════════════════════════════════════════════════════════════

    def format_quick_report(self, data: dict = None) -> str:
        """Format quick overview for terminal."""
        d = data or self.last_results.get("quick", {})
        if not d:
            return "No data — run quick_overview() first"

        s = d.get("system", {})
        n = d.get("network", {})
        v = d.get("vpn", {})
        lines = [
            f"",
            f"🛡️  SECURITY QUICK SCAN — {d.get('timestamp', '')[:19]}",
            f"   Scan time: {d.get('scan_time_sec', '?')}s",
            f"",
            f"   💻 System:  CPU {s.get('cpu_pct', '?')}% | RAM {s.get('mem_used_gb', '?')}/{s.get('mem_total_gb', '?')}GB ({s.get('mem_pct', '?')}%) | Disk {s.get('disk_pct', '?')}%",
            f"   🌐 Network: {n.get('total_connections', '?')} connections | {n.get('listening_ports', '?')} listening | {n.get('established', '?')} established | {n.get('unique_remote_ips', '?')} remote IPs",
            f"   🔒 VPN:     {'✓ UP (' + (v.get('interface') or '') + ')' if v.get('active') else '✗ DOWN'}",
            f"",
        ]

        # Exposed services
        exposed = d.get("exposed_services", [])
        if exposed:
            lines.append(f"   ⚠️  Exposed services ({len(exposed)}):")
            for svc in exposed[:8]:
                lines.append(f"      :{svc['port']} — {svc['process']}")
            if len(exposed) > 8:
                lines.append(f"      ... +{len(exposed) - 8} more")
            lines.append("")

        # Top processes
        top = n.get("top_processes", {})
        if top:
            lines.append(f"   📊 Top processes by connections:")
            for proc, count in list(top.items())[:5]:
                lines.append(f"      {proc}: {count}")
            lines.append("")

        # Warnings
        warnings = d.get("warnings", [])
        if warnings:
            lines.append(f"   🚨 Warnings:")
            for w in warnings:
                lines.append(f"      • {w}")
            lines.append("")

        risk = d.get("risk_level", "?")
        risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(risk, "⚪")
        lines.append(f"   {risk_icon} Risk level: {risk}")

        return "\n".join(lines)

    def format_full_audit_report(self, data: dict = None) -> str:
        """Format full audit for terminal."""
        d = data or self.last_results.get("full_audit", {})
        if not d:
            return "No data — run full_audit() first"

        lines = [
            "",
            "═" * 70,
            " LARRY G-FORCE — FULL SECURITY AUDIT REPORT",
            "═" * 70,
            f" Time: {d.get('timestamp', '')[:19]}  |  Duration: {d.get('total_time_sec', '?')}s",
            f" Network: {d.get('network', '?')}",
            f" Modules: {d.get('modules_available', '?')}/{d.get('modules_total', '?')} ran successfully",
            "",
        ]

        # Quick overview section
        overview = d.get("overview", {})
        if overview:
            lines.append(self.format_quick_report(overview))
            lines.append("")

        # Investigation section
        inv = d.get("investigation", {})
        if inv and not inv.get("error"):
            summary = inv.get("summary", {})
            lines.append("─" * 70)
            lines.append(" 🔍 PORT INVESTIGATION")
            lines.append(f"   {summary.get('total', 0)} connections | {summary.get('established', 0)} active | {summary.get('listening', 0)} listening")
            lines.append(f"   {summary.get('unique_remote_ips', 0)} unique remote IPs | {summary.get('countries_connected', 0)} countries")

            by_country = inv.get("by_country", {})
            if by_country:
                top_countries = sorted(by_country.items(), key=lambda x: -x[1])[:5]
                lines.append(f"   Countries: {', '.join(f'{c}({n})' for c, n in top_countries)}")
            lines.append("")

        # Network hunt section
        hunt = d.get("network_hunt", {})
        if hunt and not hunt.get("error"):
            disc = hunt.get("discovery", {})
            hosts_found = len(disc.get("hosts_found", []))
            services = hunt.get("services", {})
            svc_found = len(services.get("services", []))
            issues = hunt.get("security_issues", {}).get("security_issues", [])

            lines.append("─" * 70)
            lines.append(" 🎯 NETWORK RECONNAISSANCE")
            lines.append(f"   {hosts_found} hosts discovered | {svc_found} open services")
            if issues:
                lines.append(f"   ⚠️  Security issues: {len(issues)}")
                for issue in issues[:5]:
                    lines.append(f"      [{issue.get('severity', '?').upper()}] {issue.get('issue', '')} on {issue.get('host', '?')}:{issue.get('port', '?')}")

            recs = hunt.get("security_issues", {}).get("recommendations", [])
            if recs:
                lines.append(f"   Recommendations:")
                for r in recs[:3]:
                    lines.append(f"      → {r}")
            lines.append("")

        # Traffic section
        traffic = d.get("traffic", {})
        if traffic and not traffic.get("error"):
            anomalies = traffic.get("anomalies", {}).get("anomalies", [])
            flows = traffic.get("flows", {}).get("flows", [])
            latency = traffic.get("latency", {}).get("average", {})

            lines.append("─" * 70)
            lines.append(" 📡 TRAFFIC ANALYSIS")
            lines.append(f"   {len(flows)} active flows")
            if anomalies:
                lines.append(f"   ⚠️  Anomalies: {len(anomalies)}")
                for a in anomalies[:3]:
                    lines.append(f"      [{a.get('severity', '?')}] {a.get('type', '?')}: {a.get('indicator', '')}")
            if latency:
                for host, ms in latency.items():
                    lines.append(f"   Latency to {host}: {ms:.1f}ms")
            lines.append("")

        # Firewall section
        fw = d.get("firewall", {})
        if fw and not fw.get("error"):
            fw_data = fw.get("firewall", {})
            open_ports = fw_data.get("open_ports", [])
            blocked = fw_data.get("blocked_ports", [])
            recs = fw_data.get("recommendations", [])

            lines.append("─" * 70)
            lines.append(" 🧱 FIREWALL")
            lines.append(f"   {len(open_ports)} open | {len(blocked)} blocked")
            if recs:
                for r in recs[:3]:
                    lines.append(f"   ⚠️  {r}")
            lines.append("")

        # Failed modules
        failed = d.get("modules_failed", [])
        if failed:
            lines.append("─" * 70)
            lines.append(" ⚠️  MODULES THAT FAILED:")
            for f in failed:
                lines.append(f"   ✗ {f['module']}: {f['error']}")
            lines.append("")

        # Overall
        risk = d.get("overall_risk", "?")
        risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(risk, "⚪")
        lines.append("═" * 70)
        lines.append(f" {risk_icon} OVERALL RISK: {risk}")
        lines.append("═" * 70)

        return "\n".join(lines)

    def format_telegram_alert(self, data: dict = None) -> str:
        """Compact HTML report for Telegram."""
        d = data or self.last_results.get("quick", {})
        s = d.get("system", {})
        n = d.get("network", {})
        v = d.get("vpn", {})
        risk = d.get("risk_level", "?")

        lines = [
            f"<b>🛡️ SECURITY SNAPSHOT</b>",
            f"CPU {s.get('cpu_pct', '?')}% | RAM {s.get('mem_pct', '?')}% | Disk {s.get('disk_pct', '?')}%",
            f"🌐 {n.get('established', '?')} active | {n.get('unique_remote_ips', '?')} IPs | {n.get('listening_ports', '?')} ports",
            f"🔒 VPN: {'UP' if v.get('active') else 'DOWN'}",
        ]

        warnings = d.get("warnings", [])
        if warnings:
            lines.append(f"\n⚠️ {', '.join(warnings)}")

        lines.append(f"\nRisk: <b>{risk}</b>")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════
    #  OPERATION: BASH SCRIPTS
    # ══════════════════════════════════════════════════════════════

    def run_bash_script(self, key: str, extra_args: list = None) -> Dict:
        """Run a bash security script by registry key."""
        runner = Lazy.bash_runner()
        if not runner:
            return {"error": "bash_script_runner.py not found"}
        return runner.run(key, extra_args=extra_args)

    def list_bash_scripts(self) -> Dict:
        """List all bash scripts with availability status."""
        runner = Lazy.bash_runner()
        if not runner:
            return {"error": "bash_script_runner.py not found"}
        return runner.list_scripts()

    # ══════════════════════════════════════════════════════════════
    #  DASHBOARD API (for dashboard_hub.py integration)
    # ══════════════════════════════════════════════════════════════

    def get_dashboard_data(self) -> Dict:
        """Returns all cached results for the dashboard."""
        return {
            "timestamp": datetime.now().isoformat(),
            "modules": self.check_modules(),
            "last_results": {
                k: v for k, v in self.last_results.items()
                if k in ("quick", "investigate")
            },
        }

    # ══════════════════════════════════════════════════════════════
    #  AGENT CLI COMMAND ROUTER
    # ══════════════════════════════════════════════════════════════

    def handle_command(self, cmd: str, args: str = "") -> str:
        """
        Process /security commands from agent_v2.py.
        Returns formatted string output.

        Commands:
          /security                  Quick overview
          /security quick            Same as above
          /security investigate      Full port investigation with geo
          /security investigate 443  Deep-dive specific port
          /security hunt             Network discovery + service scan
          /security hunt 10.0.0.0/24 Hunt specific network
          /security traffic          Traffic analysis
          /security firewall         Firewall test
          /security audit            Full audit (all modules)
          /security modules          Show available modules
          /security export           Export last results as JSON
        """
        parts = args.strip().split() if args.strip() else []
        subcmd = parts[0] if parts else "quick"
        subargs = parts[1:] if len(parts) > 1 else []

        if subcmd in ("quick", "overview", "status"):
            data = self.quick_overview()
            return self.format_quick_report(data)

        elif subcmd in ("investigate", "ports", "inv"):
            if subargs and subargs[0].isdigit():
                data = self.investigate_ports(port=int(subargs[0]))
                return json.dumps(data, indent=2, default=str)[:3000]
            else:
                data = self.investigate_ports()
                return self.format_investigation(data)

        elif subcmd in ("hunt", "recon", "discover"):
            network = subargs[0] if subargs else None
            data = self.network_hunt(network=network)
            disc = data.get("discovery", {})
            hosts = disc.get("hosts_found", [])
            svcs = data.get("services", {}).get("services", [])
            issues = data.get("security_issues", {}).get("security_issues", [])
            lines = [
                f"\n🎯 Network Hunt — {data.get('network', '?')}",
                f"   {len(hosts)} hosts | {len(svcs)} services | {len(issues)} issues",
            ]
            for h in hosts[:10]:
                lines.append(f"   • {h.get('ip', '?')} ({h.get('vendor', h.get('discovery_method', '?'))})")
            for i in issues[:5]:
                lines.append(f"   ⚠️  [{i.get('severity', '?')}] {i.get('issue', '')} — {i.get('host', '?')}:{i.get('port', '?')}")
            return "\n".join(lines)

        elif subcmd in ("traffic", "flows"):
            hosts = subargs or None
            data = self.analyze_traffic(hosts=hosts)
            anomalies = data.get("anomalies", {}).get("anomalies", [])
            flows = data.get("flows", {}).get("flows", [])
            lines = [f"\n📡 Traffic Analysis", f"   {len(flows)} flows | {len(anomalies)} anomalies"]
            for a in anomalies[:5]:
                lines.append(f"   ⚠️  {a.get('type', '?')}: {a.get('indicator', '')}")
            return "\n".join(lines)

        elif subcmd in ("firewall", "fw"):
            hosts = subargs or ["127.0.0.1"]
            data = self.test_firewall(hosts=hosts)
            fw = data.get("firewall", {})
            lines = [
                f"\n🧱 Firewall Test",
                f"   {len(fw.get('open_ports', []))} open | {len(fw.get('blocked_ports', []))} blocked",
            ]
            for r in fw.get("recommendations", [])[:5]:
                lines.append(f"   ⚠️  {r}")
            return "\n".join(lines)

        elif subcmd in ("audit", "full", "full-audit"):
            data = self.full_audit()
            return self.format_full_audit_report(data)

        elif subcmd in ("modules", "status-modules"):
            mods = self.check_modules()
            lines = ["\n📦 Security Modules:"]
            for name, avail in mods.items():
                icon = "✓" if avail else "✗"
                lines.append(f"   {icon} {name}")
            return "\n".join(lines)

        elif subcmd == "export":
            if self.last_results:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = f"{self.output_dir}/security_export_{ts}.json"
                with open(path, "w") as f:
                    json.dump(self.last_results, f, indent=2, default=str)
                return f"\n📁 Exported to: {path}"
            return "\nNo results to export — run a scan first"

        elif subcmd in ("bash", "scripts", "sh"):
            runner = Lazy.bash_runner()
            if not runner:
                return "\n⚠️  bash_script_runner.py not found — place it in the Agent-Larry directory"
            bash_args = " ".join(subargs) if subargs else ""
            return runner.handle_command(bash_args)

        elif subcmd in ("verify", "network-check", "net-check"):
            runner = Lazy.bash_runner()
            if not runner:
                return "\n⚠️  bash_script_runner.py not found"
            return runner.handle_command("verify")

        elif subcmd in ("scan-device", "deep-scan"):
            runner = Lazy.bash_runner()
            if not runner:
                return "\n⚠️  bash_script_runner.py not found"
            target = subargs[0] if subargs else ""
            if not target:
                return "\nUsage: /security scan-device <ip>"
            return runner.handle_command(f"scan {target}")

        elif subcmd in ("homelab", "nmap-audit"):
            runner = Lazy.bash_runner()
            if not runner:
                return "\n⚠️  bash_script_runner.py not found"
            return runner.handle_command("audit")

        elif subcmd in ("looting", "ll"):
            runner = Lazy.bash_runner()
            if not runner:
                return "\n⚠️  bash_script_runner.py not found"
            return runner.handle_command("looting")

        else:
            return (
                "\n🛡️  Security Commands:\n"
                "   /security              Quick overview\n"
                "   /security investigate   Port investigation + geo\n"
                "   /security investigate N Deep-dive port N\n"
                "   /security hunt          Network discovery\n"
                "   /security traffic       Traffic analysis\n"
                "   /security firewall      Firewall test\n"
                "   /security audit         Full audit (all modules)\n"
                "   /security modules       Show available modules\n"
                "   /security export        Export results as JSON\n"
                "   /security bash [cmd]    Run bash security scripts\n"
                "   /security verify        Network config check\n"
                "   /security scan-device <ip>  Deep scan a device\n"
                "   /security homelab       Full nmap homelab audit\n"
                "   /security looting       Looting Larry interactive"
            )

    # ── Utilities ─────────────────────────────────────────────────

    def _detect_network(self) -> str:
        """Auto-detect the local network CIDR."""
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                if iface.startswith("lo"):
                    continue
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        # Guess /24
                        parts = addr.address.split(".")
                        return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        except Exception:
            pass
        return "192.168.1.0/24"

    def _save_report(self, report_type: str, data: dict):
        """Save a report to the reports directory."""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = Path(self.output_dir) / f"{report_type}_{ts}.json"
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            log.info(f"Report saved: {path}")
            self.scan_history.append({"type": report_type, "path": str(path), "timestamp": ts})
        except Exception as e:
            log.warning(f"Failed to save report: {e}")


# ══════════════════════════════════════════════════════════════════
#  DASHBOARD API ROUTES (paste into dashboard_hub.py)
# ══════════════════════════════════════════════════════════════════

def register_security_routes(app, security_center: SecurityCommandCenter = None):
    """
    Register Flask routes for the security dashboard.
    Call this from dashboard_hub.py:
        from security_command_center import SecurityCommandCenter, register_security_routes
        sec = SecurityCommandCenter()
        register_security_routes(app, sec)
    """
    sec = security_center or SecurityCommandCenter()

    @app.route("/api/security/quick")
    def api_security_quick():
        from flask import jsonify
        return jsonify(sec.quick_overview())

    @app.route("/api/security/investigate")
    def api_security_investigate():
        from flask import jsonify, request
        port = request.args.get("port", type=int)
        no_geo = request.args.get("no_geo", "false").lower() == "true"
        return jsonify(sec.investigate_ports(port=port, no_geo=no_geo))

    @app.route("/api/security/hunt")
    def api_security_hunt():
        from flask import jsonify, request
        network = request.args.get("network")
        return jsonify(sec.network_hunt(network=network))

    @app.route("/api/security/traffic")
    def api_security_traffic():
        from flask import jsonify
        return jsonify(sec.analyze_traffic())

    @app.route("/api/security/firewall")
    def api_security_firewall():
        from flask import jsonify, request
        hosts = request.args.getlist("host") or ["127.0.0.1"]
        return jsonify(sec.test_firewall(hosts=hosts))

    @app.route("/api/security/audit")
    def api_security_audit():
        from flask import jsonify
        return jsonify(sec.full_audit())

    @app.route("/api/security/modules")
    def api_security_modules():
        from flask import jsonify
        return jsonify(sec.check_modules())

    return sec


# ══════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def interactive_menu(sec: SecurityCommandCenter):
    """Interactive menu for standalone usage."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║   LARRY G-FORCE — SECURITY COMMAND CENTER                    ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    mods = sec.check_modules()
    available = sum(1 for v in mods.values() if v)
    total = len(mods)
    print(f"\n   Modules: {available}/{total} available")
    for name, avail in mods.items():
        icon = "✓" if avail else "✗"
        print(f"   {icon} {name}")

    commands = {
        "1": ("Quick Overview", "quick"),
        "2": ("Port Investigation (with geo)", "investigate"),
        "3": ("Network Hunt (discovery + services)", "hunt"),
        "4": ("Traffic Analysis", "traffic"),
        "5": ("Firewall Test", "firewall"),
        "6": ("Full Audit (everything)", "audit"),
        "7": ("Export Last Results", "export"),
        "q": ("Quit", None),
    }

    while True:
        print("\n   ─── Operations ───")
        for key, (desc, _) in commands.items():
            print(f"   [{key}] {desc}")

        choice = input("\n   ❯ ").strip().lower()

        if choice == "q":
            print("\n   Stay safe, Batman. 🦇\n")
            break
        elif choice in commands and commands[choice][1]:
            subcmd = commands[choice][1]
            print(sec.handle_command("security", subcmd))
        else:
            print("   Unknown option")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Larry G-Force Security Command Center",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python security_command_center.py                    Interactive menu
  python security_command_center.py quick              Fast overview
  python security_command_center.py investigate        Port investigation + geo
  python security_command_center.py investigate 443    Deep-dive port 443
  python security_command_center.py hunt               Network discovery
  python security_command_center.py hunt 10.0.0.0/24   Hunt specific network
  python security_command_center.py traffic            Traffic analysis
  python security_command_center.py firewall           Firewall test
  python security_command_center.py audit              Full audit (all modules)
  python security_command_center.py modules            Show available modules
        """,
    )
    parser.add_argument("command", nargs="?", default=None,
                        choices=["quick", "investigate", "hunt", "traffic",
                                 "firewall", "audit", "modules", "export"],
                        help="Command to run")
    parser.add_argument("args", nargs="*", help="Command arguments")
    parser.add_argument("--output", default=str(REPORTS_DIR), help="Output directory")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    args = parser.parse_args()
    sec = SecurityCommandCenter(output_dir=args.output)

    if not args.command:
        interactive_menu(sec)
        return

    # Direct command execution
    subcmd = args.command
    subargs = " ".join(args.args) if args.args else ""

    if args.json:
        # JSON output mode
        if subcmd == "quick":
            print(json.dumps(sec.quick_overview(), indent=2, default=str))
        elif subcmd == "investigate":
            port = int(subargs) if subargs.isdigit() else None
            print(json.dumps(sec.investigate_ports(port=port), indent=2, default=str))
        elif subcmd == "hunt":
            print(json.dumps(sec.network_hunt(network=subargs or None), indent=2, default=str))
        elif subcmd == "traffic":
            print(json.dumps(sec.analyze_traffic(), indent=2, default=str))
        elif subcmd == "firewall":
            print(json.dumps(sec.test_firewall(), indent=2, default=str))
        elif subcmd == "audit":
            print(json.dumps(sec.full_audit(), indent=2, default=str))
        elif subcmd == "modules":
            print(json.dumps(sec.check_modules(), indent=2))
    else:
        # Formatted output
        print(sec.handle_command("security", f"{subcmd} {subargs}".strip()))


if __name__ == "__main__":
    main()
