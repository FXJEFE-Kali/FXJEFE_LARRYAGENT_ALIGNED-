#!/usr/bin/env python3
"""
Autonomous Security Toolkit
Integrates network scanning and VM management with LLM-guided operations.
Provides a unified interface for autonomous security tasks.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum

# Import our modules
from autonomous_network_security import (
    AutonomousNetworkScanner, ScanResult, HostInfo, RiskLevel, ScanType
)
from vm_manager import VMManager, VMConfig, VMInfo, VMState, VMProvider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    """Task priority levels."""
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class SecurityTask:
    """A security task to be executed."""
    task_id: str
    task_type: str
    description: str
    priority: TaskPriority
    target: Optional[str] = None
    parameters: Dict[str, Any] = None
    created_at: str = None
    scheduled_for: Optional[str] = None
    completed_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class AutonomousSecurityToolkit:
    """
    Unified security toolkit combining network scanning and VM management
    with autonomous decision-making capabilities.
    """
    
    def __init__(self, llm_client=None):
        self.network_scanner = AutonomousNetworkScanner()
        self.vm_manager = VMManager()
        self.llm_client = llm_client
        self.task_queue: List[SecurityTask] = []
        self.task_history: List[SecurityTask] = []
        self.running = False
        self.scheduled_tasks: Dict[str, asyncio.Task] = {}
        
        # Security policies
        self.policies = {
            'auto_scan_interval_minutes': 60,
            'alert_on_new_devices': True,
            'auto_snapshot_before_scan': True,
            'max_concurrent_scans': 2,
            'block_high_risk_ports': False,
        }
    
    # ========================================================================
    # Task Management
    # ========================================================================
    
    def create_task(self, task_type: str, description: str,
                    priority: TaskPriority = TaskPriority.MEDIUM,
                    target: Optional[str] = None,
                    parameters: Optional[Dict] = None,
                    schedule_delay_minutes: Optional[int] = None) -> SecurityTask:
        """Create a new security task."""
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Ensure priority is a TaskPriority enum
        if isinstance(priority, int):
            priority = TaskPriority(priority)
        elif not isinstance(priority, TaskPriority):
            priority = TaskPriority.MEDIUM
        
        scheduled_for = None
        if schedule_delay_minutes:
            scheduled_for = (datetime.now() + 
                           timedelta(minutes=schedule_delay_minutes)).isoformat()
        
        task = SecurityTask(
            task_id=task_id,
            task_type=task_type,
            description=description,
            priority=priority,
            target=target,
            parameters=parameters or {},
            scheduled_for=scheduled_for
        )
        
        self.task_queue.append(task)
        self.task_queue.sort(key=lambda t: t.priority.value if isinstance(t.priority, TaskPriority) else t.priority)
        
        logger.info(f"Created task {task_id}: {description}")
        return task
    
    def execute_task(self, task: SecurityTask) -> Any:
        """Execute a security task."""
        logger.info(f"Executing task {task.task_id}: {task.description}")
        
        try:
            if task.task_type == "network_discovery":
                result = self.network_scanner.discover_hosts(
                    task.parameters.get('network_range')
                )
            
            elif task.task_type == "port_scan":
                result = self.network_scanner.scan_ports(
                    targets=task.parameters.get('targets', [task.target]),
                    ports=task.parameters.get('ports'),
                    scan_type=task.parameters.get('scan_type', 'tcp')
                )
            
            elif task.task_type == "vulnerability_scan":
                result = self.network_scanner.scan_vulnerabilities(
                    targets=task.parameters.get('targets', [task.target])
                )
            
            elif task.task_type == "comprehensive_scan":
                result = self.network_scanner.comprehensive_scan(
                    task.parameters.get('network_range')
                )
            
            elif task.task_type == "vm_start":
                success, msg = self.vm_manager.start_vm(
                    task.target,
                    headless=task.parameters.get('headless', False)
                )
                result = {"success": success, "message": msg}
            
            elif task.task_type == "vm_stop":
                success, msg = self.vm_manager.stop_vm(
                    task.target,
                    force=task.parameters.get('force', False)
                )
                result = {"success": success, "message": msg}
            
            elif task.task_type == "vm_snapshot":
                success, msg = self.vm_manager.create_snapshot(
                    task.target,
                    task.parameters.get('snapshot_name', f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
                    task.parameters.get('description', 'Automated snapshot')
                )
                result = {"success": success, "message": msg}
            
            elif task.task_type == "vm_create":
                config = VMConfig(**task.parameters.get('config', {}))
                success, msg = self.vm_manager.create_vm(config)
                result = {"success": success, "message": msg}
            
            elif task.task_type == "detect_new_devices":
                new_devices = self.network_scanner.detect_new_devices()
                result = {"new_devices": [asdict(d) for d in new_devices]}
            
            elif task.task_type == "generate_report":
                if task.parameters.get('report_type') == 'network':
                    scan_id = task.parameters.get('scan_id')
                    if scan_id:
                        # Find the scan result
                        for scan in self.network_scanner.scan_history:
                            if scan.scan_id == scan_id:
                                result = self.network_scanner.generate_report(scan)
                                break
                    else:
                        result = self.network_scanner.get_scan_summary()
                elif task.parameters.get('report_type') == 'vm':
                    result = self.vm_manager.generate_report()
                else:
                    result = self.generate_full_report()
            
            else:
                result = {"error": f"Unknown task type: {task.task_type}"}
            
            task.result = result
            task.completed_at = datetime.now().isoformat()
            self.task_history.append(task)
            
            logger.info(f"Task {task.task_id} completed successfully")
            return result
            
        except Exception as e:
            task.error = str(e)
            task.completed_at = datetime.now().isoformat()
            self.task_history.append(task)
            logger.error(f"Task {task.task_id} failed: {e}")
            raise
    
    def process_task_queue(self) -> List[Any]:
        """Process all tasks in the queue."""
        results = []
        
        while self.task_queue:
            task = self.task_queue.pop(0)
            
            # Check if task is scheduled for later
            if task.scheduled_for:
                scheduled_time = datetime.fromisoformat(task.scheduled_for)
                if scheduled_time > datetime.now():
                    # Put back in queue and continue
                    self.task_queue.append(task)
                    self.task_queue.sort(key=lambda t: t.priority.value)
                    continue
            
            try:
                result = self.execute_task(task)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e)})
        
        return results
    
    # ========================================================================
    # Autonomous Operations
    # ========================================================================
    
    def autonomous_network_audit(self, network_range: Optional[str] = None) -> Dict[str, Any]:
        """
        Perform an autonomous network audit with intelligent analysis.
        
        This function:
        1. Discovers hosts on the network
        2. Scans for open ports
        3. Checks for vulnerabilities
        4. Analyzes risks
        5. Generates recommendations
        """
        logger.info("Starting autonomous network audit")
        
        results = {
            'scan_id': None,
            'hosts_discovered': 0,
            'ports_found': 0,
            'vulnerabilities_found': 0,
            'risk_assessment': {},
            'recommendations': [],
            'alerts': []
        }
        
        # Step 1: Comprehensive scan
        scan_result = self.network_scanner.comprehensive_scan(network_range)
        results['scan_id'] = scan_result.scan_id
        results['hosts_discovered'] = scan_result.hosts_found
        results['ports_found'] = scan_result.ports_found
        results['vulnerabilities_found'] = scan_result.vulnerabilities_found
        
        # Step 2: Risk assessment per host
        risk_distribution = {level.value: [] for level in RiskLevel}
        
        for host in scan_result.hosts:
            risk = self.network_scanner.assess_risk(host)
            risk_distribution[risk.value].append({
                'ip': host.ip,
                'hostname': host.hostname,
                'open_ports': [p['port'] for p in host.ports],
                'vulnerabilities': len(host.vulnerabilities)
            })
        
        results['risk_assessment'] = risk_distribution
        
        # Step 3: Generate recommendations
        recommendations = []
        
        # Check for high-risk hosts
        if risk_distribution['critical'] or risk_distribution['high']:
            recommendations.append({
                'priority': 'critical',
                'message': 'High-risk hosts detected. Immediate attention required.',
                'hosts': risk_distribution['critical'] + risk_distribution['high']
            })
        
        # Check for common vulnerabilities
        telnet_hosts = [h for h in scan_result.hosts 
                       if any(p['port'] == 23 for p in h.ports)]
        if telnet_hosts:
            recommendations.append({
                'priority': 'high',
                'message': 'Telnet (port 23) detected on hosts. Consider disabling.',
                'hosts': [{'ip': h.ip} for h in telnet_hosts]
            })
        
        # Check for RDP exposure
        rdp_hosts = [h for h in scan_result.hosts 
                    if any(p['port'] == 3389 for p in h.ports)]
        if rdp_hosts:
            recommendations.append({
                'priority': 'medium',
                'message': 'RDP (port 3389) exposed. Ensure strong authentication.',
                'hosts': [{'ip': h.ip} for h in rdp_hosts]
            })
        
        results['recommendations'] = recommendations
        
        # Step 4: Check for new devices
        new_devices = self.network_scanner.detect_new_devices()
        if new_devices:
            results['alerts'].append({
                'type': 'new_devices',
                'message': f'{len(new_devices)} new device(s) detected',
                'devices': [asdict(d) for d in new_devices]
            })
        
        return results
    
    def autonomous_vm_operation(self, operation: str, vm_name: str,
                                 parameters: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Perform autonomous VM operations with safety checks.
        
        Args:
            operation: Operation to perform (start, stop, restart, snapshot, etc.)
            vm_name: Name of the VM
            parameters: Additional parameters for the operation
        """
        parameters = parameters or {}
        
        logger.info(f"Autonomous VM operation: {operation} on {vm_name}")
        
        result = {
            'operation': operation,
            'vm_name': vm_name,
            'success': False,
            'message': '',
            'safety_checks': []
        }
        
        # Get current VM state
        vm_info = self.vm_manager.get_vm(vm_name)
        
        if not vm_info:
            result['message'] = f"VM '{vm_name}' not found"
            return result
        
        # Perform safety checks
        if operation == 'stop' and not parameters.get('force'):
            # Check if VM is running
            if vm_info.state != VMState.RUNNING:
                result['message'] = f"VM '{vm_name}' is not running"
                return result
            
            # Create snapshot before stopping if policy enabled
            if self.policies['auto_snapshot_before_scan']:
                snap_success, snap_msg = self.vm_manager.create_snapshot(
                    vm_name,
                    f"pre_stop_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "Auto-snapshot before stop"
                )
                result['safety_checks'].append({
                    'type': 'auto_snapshot',
                    'success': snap_success,
                    'message': snap_msg
                })
        
        # Execute operation
        if operation == 'start':
            success, msg = self.vm_manager.start_vm(
                vm_name,
                headless=parameters.get('headless', False)
            )
        elif operation == 'stop':
            success, msg = self.vm_manager.stop_vm(
                vm_name,
                force=parameters.get('force', False)
            )
        elif operation == 'restart':
            success, msg = self.vm_manager.restart_vm(vm_name)
        elif operation == 'snapshot':
            success, msg = self.vm_manager.create_snapshot(
                vm_name,
                parameters.get('snapshot_name', f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
                parameters.get('description', 'Automated snapshot')
            )
        else:
            success = False
            msg = f"Unknown operation: {operation}"
        
        result['success'] = success
        result['message'] = msg
        
        return result
    
    def schedule_recurring_scan(self, interval_minutes: int = 60,
                                 network_range: Optional[str] = None) -> SecurityTask:
        """Schedule a recurring network scan."""
        return self.create_task(
            task_type="comprehensive_scan",
            description=f"Recurring network scan (every {interval_minutes} minutes)",
            priority=TaskPriority.MEDIUM,
            parameters={'network_range': network_range},
            schedule_delay_minutes=interval_minutes
        )
    
    # ========================================================================
    # LLM Integration
    # ========================================================================
    
    def set_llm_client(self, client):
        """Set the LLM client for intelligent decision making."""
        self.llm_client = client
    
    def analyze_with_llm(self, data: Any, analysis_type: str = "general") -> str:
        """Analyze security data using LLM."""
        if not self.llm_client:
            return "LLM client not configured"
        
        # Prepare prompt based on analysis type
        if analysis_type == "network_scan":
            prompt = self._create_network_analysis_prompt(data)
        elif analysis_type == "risk_assessment":
            prompt = self._create_risk_analysis_prompt(data)
        elif analysis_type == "recommendations":
            prompt = self._create_recommendations_prompt(data)
        else:
            prompt = f"Analyze the following security data:\n\n{json.dumps(data, indent=2)}"
        
        try:
            # This would call the LLM client
            # response = self.llm_client.generate(prompt)
            # return response
            return f"[LLM Analysis] Would analyze with prompt: {prompt[:100]}..."
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            return f"LLM analysis failed: {e}"
    
    def _create_network_analysis_prompt(self, scan_result: ScanResult) -> str:
        """Create a prompt for network scan analysis."""
        return f"""Analyze this network scan result and provide insights:

Scan ID: {scan_result.scan_id}
Network Range: {scan_result.network_range}
Hosts Found: {scan_result.hosts_found}
Open Ports: {scan_result.ports_found}
Vulnerabilities: {scan_result.vulnerabilities_found}

Hosts:
{json.dumps([asdict(h) for h in scan_result.hosts], indent=2)}

Please provide:
1. Summary of findings
2. Security concerns
3. Recommendations for improvement
"""
    
    def _create_risk_analysis_prompt(self, risk_data: Dict) -> str:
        """Create a prompt for risk analysis."""
        return f"""Analyze this risk assessment and prioritize actions:

Risk Distribution:
{json.dumps(risk_data, indent=2)}

Please provide:
1. Risk prioritization
2. Immediate actions needed
3. Long-term security improvements
"""
    
    def _create_recommendations_prompt(self, context: Dict) -> str:
        """Create a prompt for generating recommendations."""
        return f"""Based on the following security context, provide actionable recommendations:

Context:
{json.dumps(context, indent=2)}

Please provide:
1. Immediate security actions
2. Configuration improvements
3. Monitoring recommendations
"""
    
    # ========================================================================
    # Reporting
    # ========================================================================
    
    def generate_full_report(self) -> Dict[str, Any]:
        """Generate a comprehensive security report."""
        network_summary = self.network_scanner.get_scan_summary()
        vm_report = self.vm_manager.generate_report()
        
        return {
            'generated_at': datetime.now().isoformat(),
            'network_security': network_summary,
            'virtual_machines': vm_report,
            'recent_tasks': len([t for t in self.task_history 
                                if t.completed_at and 
                                datetime.fromisoformat(t.completed_at) > 
                                datetime.now() - timedelta(hours=24)]),
            'pending_tasks': len(self.task_queue),
            'policies': self.policies
        }
    
    def generate_text_report(self) -> str:
        """Generate a human-readable text report."""
        report_data = self.generate_full_report()
        
        lines = [
            "=" * 80,
            "AUTONOMOUS SECURITY TOOLKIT - COMPREHENSIVE REPORT",
            "=" * 80,
            f"Generated: {report_data['generated_at']}",
            "",
            "NETWORK SECURITY STATUS",
            "-" * 80,
            f"Total Scans: {report_data['network_security']['total_scans']}",
            f"Known Hosts: {report_data['network_security']['total_known_hosts']}",
            f"Total Vulnerabilities: {report_data['network_security']['total_vulnerabilities']}",
            "",
            "Risk Distribution:",
        ]
        
        for risk, count in report_data['network_security']['risk_distribution'].items():
            lines.append(f"  {risk.upper()}: {count} hosts")
        
        lines.extend([
            "",
            "VIRTUAL MACHINES",
            "-" * 80,
        ])
        
        # Add VM report
        lines.append(report_data['virtual_machines'])
        
        lines.extend([
            "",
            "TASK ACTIVITY (Last 24 hours)",
            "-" * 80,
            f"Completed Tasks: {report_data['recent_tasks']}",
            f"Pending Tasks: {report_data['pending_tasks']}",
            "",
            "ACTIVE POLICIES",
            "-" * 80,
        ])
        
        for policy, value in report_data['policies'].items():
            lines.append(f"  {policy}: {value}")
        
        lines.extend([
            "",
            "=" * 80,
            "END OF REPORT"
        ])
        
        return '\n'.join(lines)
    
    # ========================================================================
    # Interactive Commands
    # ========================================================================
    
    def execute_command(self, command: str) -> Dict[str, Any]:
        """
        Execute a natural language security command.
        
        Examples:
        - "scan my network"
        - "start vm Kali"
        - "check for vulnerabilities"
        - "create snapshot of Windows10"
        """
        command = command.lower().strip()
        
        # Parse command
        if 'scan' in command or 'discover' in command:
            if 'network' in command or 'my' in command:
                result = self.network_scanner.comprehensive_scan()
                return {
                    'success': True,
                    'action': 'network_scan',
                    'result': {
                        'hosts_found': result.hosts_found,
                        'ports_found': result.ports_found,
                        'vulnerabilities': result.vulnerabilities_found
                    }
                }
            elif 'port' in command:
                # Extract target if specified
                match = re.search(r'(?:on|target)\s+(\S+)', command)
                target = match.group(1) if match else None
                if target:
                    result = self.network_scanner.scan_ports([target])
                    return {
                        'success': True,
                        'action': 'port_scan',
                        'result': asdict(result)
                    }
        
        elif 'vulnerability' in command or 'vuln' in command:
            match = re.search(r'(?:on|target)\s+(\S+)', command)
            target = match.group(1) if match else None
            if target:
                result = self.network_scanner.scan_vulnerabilities([target])
                return {
                    'success': True,
                    'action': 'vulnerability_scan',
                    'result': asdict(result)
                }
        
        elif 'start' in command and 'vm' in command:
            match = re.search(r'vm\s+(\S+)', command)
            if match:
                vm_name = match.group(1)
                success, msg = self.vm_manager.start_vm(vm_name)
                return {
                    'success': success,
                    'action': 'vm_start',
                    'message': msg
                }
        
        elif 'stop' in command and 'vm' in command:
            match = re.search(r'vm\s+(\S+)', command)
            if match:
                vm_name = match.group(1)
                success, msg = self.vm_manager.stop_vm(vm_name)
                return {
                    'success': success,
                    'action': 'vm_stop',
                    'message': msg
                }
        
        elif 'snapshot' in command:
            match = re.search(r'(?:of|for)\s+(\S+)', command)
            if match:
                vm_name = match.group(1)
                success, msg = self.vm_manager.create_snapshot(
                    vm_name,
                    f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                return {
                    'success': success,
                    'action': 'vm_snapshot',
                    'message': msg
                }
        
        elif 'report' in command or 'status' in command:
            return {
                'success': True,
                'action': 'generate_report',
                'report': self.generate_text_report()
            }
        
        elif 'new device' in command or 'check device' in command:
            new_devices = self.network_scanner.detect_new_devices()
            return {
                'success': True,
                'action': 'detect_new_devices',
                'new_devices': [asdict(d) for d in new_devices]
            }
        
        return {
            'success': False,
            'error': f"Could not understand command: '{command}'"
        }


# Convenience functions
def quick_network_audit(network_range: Optional[str] = None) -> Dict:
    """Perform a quick network audit."""
    toolkit = AutonomousSecurityToolkit()
    return toolkit.autonomous_network_audit(network_range)


def scan_and_report(network_range: Optional[str] = None) -> str:
    """Scan network and return a report."""
    toolkit = AutonomousSecurityToolkit()
    audit = toolkit.autonomous_network_audit(network_range)
    
    lines = [
        "=" * 70,
        "NETWORK SECURITY AUDIT REPORT",
        "=" * 70,
        f"Scan ID: {audit['scan_id']}",
        f"Hosts Discovered: {audit['hosts_discovered']}",
        f"Open Ports: {audit['ports_found']}",
        f"Vulnerabilities: {audit['vulnerabilities_found']}",
        "",
        "RISK ASSESSMENT",
        "-" * 70,
    ]
    
    for risk, hosts in audit['risk_assessment'].items():
        lines.append(f"{risk.upper()}: {len(hosts)} hosts")
    
    if audit['recommendations']:
        lines.extend([
            "",
            "RECOMMENDATIONS",
            "-" * 70,
        ])
        for rec in audit['recommendations']:
            lines.append(f"[{rec['priority'].upper()}] {rec['message']}")
    
    if audit['alerts']:
        lines.extend([
            "",
            "ALERTS",
            "-" * 70,
        ])
        for alert in audit['alerts']:
            lines.append(f"[{alert['type'].upper()}] {alert['message']}")
    
    lines.extend(["", "=" * 70])
    
    return '\n'.join(lines)


def vm_control(operation: str, vm_name: str, **kwargs) -> Dict:
    """Control a VM with the given operation."""
    toolkit = AutonomousSecurityToolkit()
    return toolkit.autonomous_vm_operation(operation, vm_name, kwargs)


if __name__ == "__main__":
    print("=" * 80)
    print("AUTONOMOUS SECURITY TOOLKIT")
    print("=" * 80)
    print()
    
    toolkit = AutonomousSecurityToolkit()
    
    # Demo: Execute some commands
    print("[Demo] Available commands:")
    print("  - scan my network")
    print("  - check for vulnerabilities")
    print("  - start vm <name>")
    print("  - create snapshot of <vm_name>")
    print("  - report")
    print()
    
    # Show VM report
    print(toolkit.vm_manager.generate_report())
