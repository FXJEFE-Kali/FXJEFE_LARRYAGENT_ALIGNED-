# ============================================================================
# LOOTING LARRY - WINDOWS NETWORK SECURITY SCANNER
# Full network discovery, port scanning, vulnerability detection, user logging
# ============================================================================

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"  # Speed up Invoke-WebRequest etc.

# ============================================================================
# CONFIGURATION
# ============================================================================

$SCAN_DIR = "$PSScriptRoot\scan_results"
$TIMESTAMP = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$REPORT_DIR = "$SCAN_DIR\scan_$TIMESTAMP"
$DB_FILE = "$SCAN_DIR\looting_larry.sqlite"

New-Item -ItemType Directory -Path $REPORT_DIR -Force | Out-Null

# Colors
function Write-Banner {
    $banner = @"

    ╔═══════════════════════════════════════════════════════════════════════╗
    ║           ██╗      ██████╗  ██████╗ ████████╗██╗███╗   ██╗ ██████╗  ║
    ║           ██║     ██╔═══██╗██╔═══██╗╚══██╔══╝██║████╗  ██║██╔════╝  ║
    ║           ██║     ██║   ██║██║   ██║   ██║   ██║██╔██╗ ██║██║  ███╗ ║
    ║           ██║     ██║   ██║██║   ██║   ██║   ██║██║╚██╗██║██║   ██║ ║
    ║           ███████╗╚██████╔╝╚██████╔╝   ██║   ██║██║ ╚████║╚██████╔╝ ║
    ║           ╚══════╝ ╚═════╝  ╚═════╝    ╚═╝   ╚═╝╚═╝  ╚═══╝ ╚═════╝  ║
    ║              ██╗      █████╗ ██████╗ ██████╗ ██╗   ██╗               ║
    ║              ██║     ██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝               ║
    ║              ██║     ███████║██████╔╝██████╔╝ ╚████╔╝                ║
    ║              ██║     ██╔══██║██╔══██╗██╔══██╗  ╚██╔╝                 ║
    ║              ███████╗██║  ██║██║  ██║██║  ██║   ██║                  ║
    ║              ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝                  ║
    ║                                                                       ║
    ║        WINDOWS SECURITY SCANNER - Network Discovery & Audit           ║
    ║                 NordVPN Bypass Mode • PowerShell Native               ║
    ╚═══════════════════════════════════════════════════════════════════════╝

"@
    Write-Host $banner -ForegroundColor Red
}

# ============================================================================
# 1. NETWORK DISCOVERY - Find all hosts on the network
# ============================================================================

function Invoke-NetworkDiscovery {
    Write-Host "`n[1/8] NETWORK DISCOVERY" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $localIP = "10.0.0.100"
    $gateway = "10.0.0.138"
    $subnet = "10.0.0"
    $results = @()

    Write-Host "[*] Scanning $subnet.0/24 ..." -ForegroundColor Yellow
    Write-Host "[*] This will take 1-2 minutes..." -ForegroundColor DarkYellow

    # Method 1: ARP cache (instant - already known hosts)
    Write-Host "[*] Checking ARP cache..." -ForegroundColor Yellow
    $arpEntries = arp -a | Where-Object { $_ -match '^\s+\d+\.\d+\.\d+\.\d+' } | ForEach-Object {
        if ($_ -match '(\d+\.\d+\.\d+\.\d+)\s+([\w-]+)\s+(\w+)') {
            [PSCustomObject]@{
                IP = $Matches[1]
                MAC = $Matches[2]
                Type = $Matches[3]
                Source = "ARP"
            }
        }
    }

    foreach ($entry in $arpEntries) {
        if ($entry.IP -like "$subnet.*" -and $entry.Type -eq "dynamic") {
            Write-Host "  [+] ARP: $($entry.IP) MAC=$($entry.MAC)" -ForegroundColor Green
            $results += $entry
        }
    }

    # Method 2: Ping sweep (finds active hosts)
    Write-Host "[*] Running ping sweep on $subnet.1-254..." -ForegroundColor Yellow

    $pingJobs = @()
    1..254 | ForEach-Object {
        $ip = "$subnet.$_"
        $pingJobs += [PSCustomObject]@{
            IP = $ip
            Task = (New-Object System.Net.NetworkInformation.Ping).SendPingAsync($ip, 500)
        }
    }

    # Wait for all pings
    [System.Threading.Tasks.Task]::WaitAll($pingJobs.Task)

    foreach ($job in $pingJobs) {
        try {
            $reply = $job.Task.Result
            if ($reply.Status -eq 'Success') {
                $ip = $job.IP
                $existing = $results | Where-Object { $_.IP -eq $ip }
                if (-not $existing) {
                    Write-Host "  [+] PING: $ip (RTT: $($reply.RoundtripTime)ms)" -ForegroundColor Green
                    $results += [PSCustomObject]@{
                        IP = $ip
                        MAC = "Unknown"
                        Type = "ping-reply"
                        Source = "PING"
                    }
                }
            }
        } catch {}
    }

    # Refresh ARP cache after ping sweep
    Start-Sleep -Seconds 1
    $arpRefresh = arp -a | Where-Object { $_ -match '^\s+\d+\.\d+\.\d+\.\d+' } | ForEach-Object {
        if ($_ -match '(\d+\.\d+\.\d+\.\d+)\s+([\w-]+)\s+(\w+)') {
            [PSCustomObject]@{ IP = $Matches[1]; MAC = $Matches[2] }
        }
    }

    # Update MACs from ARP
    foreach ($r in $results) {
        if ($r.MAC -eq "Unknown") {
            $arpMatch = $arpRefresh | Where-Object { $_.IP -eq $r.IP }
            if ($arpMatch) { $r.MAC = $arpMatch.MAC }
        }
    }

    # Method 3: DNS/NetBIOS resolution
    Write-Host "[*] Resolving hostnames..." -ForegroundColor Yellow
    foreach ($r in $results) {
        try {
            $dns = [System.Net.Dns]::GetHostEntry($r.IP)
            $r | Add-Member -NotePropertyName "Hostname" -NotePropertyValue $dns.HostName -Force
            Write-Host "  [+] DNS: $($r.IP) -> $($dns.HostName)" -ForegroundColor Green
        } catch {
            $r | Add-Member -NotePropertyName "Hostname" -NotePropertyValue "" -Force
        }
    }

    Write-Host "`n[+] Discovered $($results.Count) hosts" -ForegroundColor Green
    $results | Export-Csv "$REPORT_DIR\01_discovered_hosts.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "[+] Saved: 01_discovered_hosts.csv" -ForegroundColor DarkGreen

    return $results
}

# ============================================================================
# 2. PORT SCANNING - Check common ports on each host
# ============================================================================

function Invoke-PortScan {
    param([array]$Hosts)

    Write-Host "`n[2/8] PORT SCANNING" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    # Common ports with service names and security risk levels
    $ports = @(
        @{Port=21;  Service="FTP";           Risk="HIGH"},
        @{Port=22;  Service="SSH";           Risk="MEDIUM"},
        @{Port=23;  Service="Telnet";        Risk="CRITICAL"},
        @{Port=25;  Service="SMTP";          Risk="MEDIUM"},
        @{Port=53;  Service="DNS";           Risk="LOW"},
        @{Port=80;  Service="HTTP";          Risk="LOW"},
        @{Port=110; Service="POP3";          Risk="HIGH"},
        @{Port=135; Service="RPC/DCOM";      Risk="HIGH"},
        @{Port=137; Service="NetBIOS-NS";    Risk="HIGH"},
        @{Port=138; Service="NetBIOS-DGM";   Risk="HIGH"},
        @{Port=139; Service="NetBIOS-SSN";   Risk="HIGH"},
        @{Port=143; Service="IMAP";          Risk="MEDIUM"},
        @{Port=389; Service="LDAP";          Risk="HIGH"},
        @{Port=443; Service="HTTPS";         Risk="LOW"},
        @{Port=445; Service="SMB";           Risk="CRITICAL"},
        @{Port=993; Service="IMAPS";         Risk="LOW"},
        @{Port=995; Service="POP3S";         Risk="LOW"},
        @{Port=1433; Service="MSSQL";        Risk="CRITICAL"},
        @{Port=1434; Service="MSSQL-UDP";    Risk="CRITICAL"},
        @{Port=1723; Service="PPTP-VPN";     Risk="HIGH"},
        @{Port=3306; Service="MySQL";        Risk="CRITICAL"},
        @{Port=3389; Service="RDP";          Risk="CRITICAL"},
        @{Port=5432; Service="PostgreSQL";   Risk="CRITICAL"},
        @{Port=5900; Service="VNC";          Risk="CRITICAL"},
        @{Port=5985; Service="WinRM-HTTP";   Risk="HIGH"},
        @{Port=5986; Service="WinRM-HTTPS";  Risk="MEDIUM"},
        @{Port=6379; Service="Redis";        Risk="CRITICAL"},
        @{Port=8080; Service="HTTP-Alt";     Risk="MEDIUM"},
        @{Port=8443; Service="HTTPS-Alt";    Risk="LOW"},
        @{Port=8888; Service="HTTP-Proxy";   Risk="MEDIUM"},
        @{Port=9090; Service="WebAdmin";     Risk="HIGH"},
        @{Port=9200; Service="Elasticsearch";Risk="CRITICAL"},
        @{Port=11434;Service="Ollama-LLM";   Risk="MEDIUM"},
        @{Port=27017;Service="MongoDB";      Risk="CRITICAL"},
        @{Port=49152;Service="DynRPC";       Risk="MEDIUM"}
    )

    $allOpenPorts = @()

    foreach ($host_ in $Hosts) {
        $ip = $host_.IP
        Write-Host "[*] Scanning $ip ($($host_.Hostname))..." -ForegroundColor Yellow

        foreach ($p in $ports) {
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $connect = $tcp.BeginConnect($ip, $p.Port, $null, $null)
                $wait = $connect.AsyncWaitHandle.WaitOne(300, $false)

                if ($wait -and $tcp.Connected) {
                    $color = switch ($p.Risk) {
                        "CRITICAL" { "Red" }
                        "HIGH"     { "DarkYellow" }
                        "MEDIUM"   { "Yellow" }
                        default    { "Green" }
                    }
                    Write-Host "  [+] $($ip):$($p.Port) OPEN - $($p.Service) [Risk: $($p.Risk)]" -ForegroundColor $color

                    # Try to grab banner
                    $banner = ""
                    try {
                        $stream = $tcp.GetStream()
                        $stream.ReadTimeout = 500
                        $buffer = New-Object byte[] 1024
                        if ($stream.DataAvailable) {
                            $bytesRead = $stream.Read($buffer, 0, $buffer.Length)
                            $banner = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $bytesRead).Trim()
                        }
                    } catch {}

                    $allOpenPorts += [PSCustomObject]@{
                        IP = $ip
                        Hostname = $host_.Hostname
                        Port = $p.Port
                        Service = $p.Service
                        Risk = $p.Risk
                        Status = "OPEN"
                        Banner = $banner
                        ScanTime = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
                    }
                }
                $tcp.Close()
            } catch {
                if ($tcp) { $tcp.Close() }
            }
        }
    }

    Write-Host "`n[+] Found $($allOpenPorts.Count) open ports across $($Hosts.Count) hosts" -ForegroundColor Green
    $allOpenPorts | Export-Csv "$REPORT_DIR\02_open_ports.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "[+] Saved: 02_open_ports.csv" -ForegroundColor DarkGreen

    return $allOpenPorts
}

# ============================================================================
# 3. SECURITY WEAKPOINT ANALYSIS
# ============================================================================

function Invoke-WeakpointAnalysis {
    param([array]$OpenPorts, [array]$Hosts)

    Write-Host "`n[3/8] SECURITY WEAKPOINT ANALYSIS" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $weakpoints = @()

    # Check for critical services exposed
    $criticalExposures = @{
        23   = "Telnet is unencrypted. All traffic including passwords transmitted in cleartext. REPLACE WITH SSH."
        21   = "FTP transmits credentials in cleartext. Use SFTP or FTPS instead."
        445  = "SMB exposed. Vulnerable to EternalBlue (MS17-010), WannaCry, NotPetya. Disable if not needed or restrict with firewall."
        3389 = "RDP exposed. Target for brute-force attacks, BlueKeep (CVE-2019-0708). Enable NLA, use VPN, restrict source IPs."
        135  = "DCOM/RPC exposed. Used in lateral movement attacks. Block at firewall."
        137  = "NetBIOS Name Service exposed. Enables network enumeration. Disable NetBIOS over TCP/IP."
        138  = "NetBIOS Datagram exposed. Used for network browsing attacks."
        139  = "NetBIOS Session exposed. Legacy file sharing - vulnerable to null session attacks."
        1433 = "MSSQL exposed. Target for sa brute-force. Restrict access, use Windows Auth."
        3306 = "MySQL exposed. Default configs often have no root password. Bind to localhost."
        5432 = "PostgreSQL exposed. Check pg_hba.conf for overly permissive access rules."
        5900 = "VNC exposed. Often weak or no authentication. Use SSH tunnel instead."
        6379 = "Redis exposed with no auth by default. Attackers can write SSH keys. BIND TO LOCALHOST."
        9200 = "Elasticsearch exposed. No auth by default - full data access. Enable X-Pack security."
        27017= "MongoDB exposed. Default: no authentication. Full database access to anyone."
        5985 = "WinRM HTTP exposed. Can be used for remote code execution. Restrict to trusted IPs."
        389  = "LDAP exposed. Can leak directory information. Use LDAPS (636) with certificate."
        110  = "POP3 - unencrypted email retrieval. Use POP3S (995) instead."
        1723 = "PPTP VPN - cryptographically broken. Use WireGuard or OpenVPN instead."
    }

    foreach ($port in $OpenPorts) {
        if ($criticalExposures.ContainsKey($port.Port)) {
            $weakpoints += [PSCustomObject]@{
                Category = "EXPOSED SERVICE"
                Severity = $port.Risk
                Host = $port.IP
                Hostname = $port.Hostname
                Port = $port.Port
                Service = $port.Service
                Finding = $criticalExposures[$port.Port]
                Remediation = "Block port $($port.Port) at firewall or restrict to trusted IPs only"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] $($port.Risk): $($port.IP):$($port.Port) ($($port.Service)) - $($criticalExposures[$port.Port].Substring(0, [Math]::Min(80, $criticalExposures[$port.Port].Length)))..." -ForegroundColor $(if ($port.Risk -eq "CRITICAL") { "Red" } else { "Yellow" })
        }
    }

    # Check for hosts with too many open ports
    $hostPortCounts = $OpenPorts | Group-Object IP
    foreach ($group in $hostPortCounts) {
        if ($group.Count -ge 5) {
            $weakpoints += [PSCustomObject]@{
                Category = "EXCESSIVE EXPOSURE"
                Severity = "HIGH"
                Host = $group.Name
                Hostname = ($Hosts | Where-Object { $_.IP -eq $group.Name }).Hostname
                Port = "Multiple"
                Service = "$($group.Count) open ports"
                Finding = "Host has $($group.Count) open ports. Large attack surface increases compromise risk."
                Remediation = "Review all services and disable unnecessary ones. Apply principle of least privilege."
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] HIGH: $($group.Name) has $($group.Count) open ports - excessive attack surface" -ForegroundColor DarkYellow
        }
    }

    # Check local Windows security
    Write-Host "`n[*] Checking local Windows security..." -ForegroundColor Yellow

    # Firewall status
    $firewallProfiles = Get-NetFirewallProfile -ErrorAction SilentlyContinue
    foreach ($profile in $firewallProfiles) {
        if (-not $profile.Enabled) {
            $weakpoints += [PSCustomObject]@{
                Category = "FIREWALL DISABLED"
                Severity = "CRITICAL"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "N/A"
                Service = "Windows Firewall"
                Finding = "$($profile.Name) firewall profile is DISABLED. System is exposed to all network attacks."
                Remediation = "Enable Windows Firewall: Set-NetFirewallProfile -Name $($profile.Name) -Enabled True"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] CRITICAL: Windows Firewall '$($profile.Name)' profile is DISABLED" -ForegroundColor Red
        } else {
            Write-Host "  [OK] Firewall '$($profile.Name)' profile: Enabled" -ForegroundColor Green
        }
    }

    # Windows Update status
    try {
        $lastUpdate = (Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 1).InstalledOn
        $daysSinceUpdate = (New-TimeSpan -Start $lastUpdate -End (Get-Date)).Days
        if ($daysSinceUpdate -gt 30) {
            $weakpoints += [PSCustomObject]@{
                Category = "MISSING UPDATES"
                Severity = "HIGH"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "N/A"
                Service = "Windows Update"
                Finding = "Last Windows update was $daysSinceUpdate days ago ($lastUpdate). Known vulnerabilities may be unpatched."
                Remediation = "Run Windows Update immediately. Consider enabling automatic updates."
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] HIGH: Last Windows update was $daysSinceUpdate days ago" -ForegroundColor DarkYellow
        } else {
            Write-Host "  [OK] Windows updates current (last: $daysSinceUpdate days ago)" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [?] Could not check Windows Update status" -ForegroundColor DarkYellow
    }

    # Check for default/weak SMB settings
    try {
        $smb1 = Get-SmbServerConfiguration -ErrorAction SilentlyContinue
        if ($smb1.EnableSMB1Protocol) {
            $weakpoints += [PSCustomObject]@{
                Category = "LEGACY PROTOCOL"
                Severity = "CRITICAL"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "445"
                Service = "SMBv1"
                Finding = "SMBv1 is ENABLED. Vulnerable to EternalBlue, WannaCry, NotPetya ransomware."
                Remediation = "Disable SMBv1: Disable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] CRITICAL: SMBv1 is ENABLED - WannaCry/EternalBlue vulnerable!" -ForegroundColor Red
        } else {
            Write-Host "  [OK] SMBv1: Disabled" -ForegroundColor Green
        }
    } catch {}

    # Check for open shares
    try {
        $shares = Get-SmbShare -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch '^\$' -and $_.Name -ne 'IPC$' }
        foreach ($share in $shares) {
            $weakpoints += [PSCustomObject]@{
                Category = "OPEN SHARE"
                Severity = "MEDIUM"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "445"
                Service = "SMB Share: $($share.Name)"
                Finding = "Non-default share '$($share.Name)' at path '$($share.Path)'. Check permissions."
                Remediation = "Review share permissions. Remove if not needed: Remove-SmbShare -Name '$($share.Name)'"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] MEDIUM: Open share: $($share.Name) -> $($share.Path)" -ForegroundColor Yellow
        }
    } catch {}

    # Check Remote Desktop status
    try {
        $rdp = Get-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -ErrorAction SilentlyContinue
        if ($rdp.fDenyTSConnections -eq 0) {
            $weakpoints += [PSCustomObject]@{
                Category = "REMOTE ACCESS"
                Severity = "HIGH"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "3389"
                Service = "Remote Desktop"
                Finding = "Remote Desktop is ENABLED. Brute-force target. Check NLA requirement."
                Remediation = "Disable RDP if not needed, or enable NLA and restrict source IPs."
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] HIGH: Remote Desktop is ENABLED" -ForegroundColor DarkYellow
        } else {
            Write-Host "  [OK] Remote Desktop: Disabled" -ForegroundColor Green
        }
    } catch {}

    # Check for guest account
    try {
        $guest = Get-LocalUser -Name "Guest" -ErrorAction SilentlyContinue
        if ($guest -and $guest.Enabled) {
            $weakpoints += [PSCustomObject]@{
                Category = "WEAK AUTH"
                Severity = "HIGH"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "N/A"
                Service = "Guest Account"
                Finding = "Guest account is ENABLED. Allows anonymous access to the system."
                Remediation = "Disable guest account: Disable-LocalUser -Name 'Guest'"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] HIGH: Guest account is ENABLED" -ForegroundColor DarkYellow
        } else {
            Write-Host "  [OK] Guest account: Disabled" -ForegroundColor Green
        }
    } catch {}

    # Check password policy
    try {
        $pwdPolicy = net accounts 2>&1
        $minLength = ($pwdPolicy | Select-String "Minimum password length" | ForEach-Object { $_ -replace '.*:\s*', '' }).Trim()
        if ($minLength -and [int]$minLength -lt 8) {
            $weakpoints += [PSCustomObject]@{
                Category = "WEAK PASSWORD POLICY"
                Severity = "HIGH"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "N/A"
                Service = "Password Policy"
                Finding = "Minimum password length is $minLength characters. Should be at least 12."
                Remediation = "Set minimum password length: net accounts /minpwlen:12"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] HIGH: Minimum password length is only $minLength chars" -ForegroundColor DarkYellow
        }
    } catch {}

    # Check for auto-login
    try {
        $autoLogin = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name "AutoAdminLogon" -ErrorAction SilentlyContinue
        if ($autoLogin.AutoAdminLogon -eq "1") {
            $weakpoints += [PSCustomObject]@{
                Category = "WEAK AUTH"
                Severity = "CRITICAL"
                Host = "localhost"
                Hostname = $env:COMPUTERNAME
                Port = "N/A"
                Service = "Auto-Login"
                Finding = "Automatic login is ENABLED. Password may be stored in plaintext in registry."
                Remediation = "Disable auto-login in registry: HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\AutoAdminLogon = 0"
                DetectedAt = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            }
            Write-Host "  [!] CRITICAL: Auto-login is ENABLED - password in registry!" -ForegroundColor Red
        }
    } catch {}

    Write-Host "`n[+] Found $($weakpoints.Count) security weakpoints" -ForegroundColor $(if ($weakpoints.Count -gt 0) { "Red" } else { "Green" })
    $weakpoints | Export-Csv "$REPORT_DIR\03_security_weakpoints.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "[+] Saved: 03_security_weakpoints.csv" -ForegroundColor DarkGreen

    return $weakpoints
}

# ============================================================================
# 4. NETWORK USER / CONNECTION LOGGING
# ============================================================================

function Get-NetworkUsers {
    Write-Host "`n[4/8] NETWORK USERS & CONNECTION LOGGING" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $allConnections = @()

    # Active TCP connections
    Write-Host "[*] Logging active TCP connections..." -ForegroundColor Yellow
    $tcpConns = Get-NetTCPConnection -State Established, Listen, TimeWait, CloseWait -ErrorAction SilentlyContinue

    foreach ($conn in $tcpConns) {
        $processName = ""
        try {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            $processName = $proc.ProcessName
        } catch {}

        $remoteHostname = ""
        if ($conn.RemoteAddress -ne "0.0.0.0" -and $conn.RemoteAddress -ne "::" -and $conn.RemoteAddress -ne "127.0.0.1") {
            try { $remoteHostname = ([System.Net.Dns]::GetHostEntry($conn.RemoteAddress)).HostName } catch {}
        }

        $allConnections += [PSCustomObject]@{
            Direction = if ($conn.State -eq "Listen") { "LISTENING" } elseif ($conn.LocalPort -lt $conn.RemotePort) { "INBOUND" } else { "OUTBOUND" }
            State = $conn.State
            LocalAddress = $conn.LocalAddress
            LocalPort = $conn.LocalPort
            RemoteAddress = $conn.RemoteAddress
            RemotePort = $conn.RemotePort
            RemoteHostname = $remoteHostname
            Process = $processName
            PID = $conn.OwningProcess
            LogTime = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        }
    }

    # Display summary
    $established = $allConnections | Where-Object { $_.State -eq "Established" }
    $listening = $allConnections | Where-Object { $_.State -eq "Listen" }
    $inbound = $allConnections | Where-Object { $_.Direction -eq "INBOUND" }

    Write-Host "`n  Active Connections:   $($established.Count)" -ForegroundColor White
    Write-Host "  Listening Ports:      $($listening.Count)" -ForegroundColor White
    Write-Host "  Inbound Connections:  $($inbound.Count)" -ForegroundColor $(if ($inbound.Count -gt 0) { "Yellow" } else { "White" })

    # Show inbound connections (potential unauthorized access)
    if ($inbound.Count -gt 0) {
        Write-Host "`n  [!] INBOUND CONNECTIONS (potential entry attempts):" -ForegroundColor Red
        foreach ($ib in $inbound) {
            Write-Host "    <- $($ib.RemoteAddress):$($ib.RemotePort) -> :$($ib.LocalPort) [$($ib.Process)] $($ib.RemoteHostname)" -ForegroundColor Yellow
        }
    }

    # Show unique remote IPs connecting to this machine
    $uniqueRemotes = $established | Where-Object { $_.RemoteAddress -notmatch '^(127\.|0\.0\.|::)' } |
        Select-Object -Property RemoteAddress -Unique
    Write-Host "`n  Unique remote IPs: $($uniqueRemotes.Count)" -ForegroundColor White
    foreach ($remote in $uniqueRemotes) {
        Write-Host "    -> $($remote.RemoteAddress)" -ForegroundColor DarkCyan
    }

    # Listening services
    Write-Host "`n  [*] LISTENING SERVICES:" -ForegroundColor Yellow
    $listening | Sort-Object LocalPort -Unique | ForEach-Object {
        $bindAddr = if ($_.LocalAddress -eq "0.0.0.0" -or $_.LocalAddress -eq "::") { "ALL INTERFACES" } else { $_.LocalAddress }
        Write-Host "    :$($_.LocalPort) [$($_.Process)] bound to $bindAddr" -ForegroundColor DarkCyan
    }

    $allConnections | Export-Csv "$REPORT_DIR\04_network_connections.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "`n[+] Saved: 04_network_connections.csv" -ForegroundColor DarkGreen

    return $allConnections
}

# ============================================================================
# 5. WINDOWS EVENT LOG - LOGIN ATTEMPTS
# ============================================================================

function Get-LoginAttempts {
    Write-Host "`n[5/8] LOGIN ATTEMPTS & SECURITY EVENTS" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $loginEvents = @()

    # Event IDs: 4624=Success, 4625=Failed, 4648=Explicit creds, 4634=Logoff
    Write-Host "[*] Querying Security Event Log (last 7 days)..." -ForegroundColor Yellow

    $startDate = (Get-Date).AddDays(-7)

    # Successful logins
    try {
        $successLogins = Get-WinEvent -FilterHashtable @{LogName='Security'; ID=4624; StartTime=$startDate} -MaxEvents 200 -ErrorAction SilentlyContinue
        foreach ($event in $successLogins) {
            $xml = [xml]$event.ToXml()
            $data = $xml.Event.EventData.Data
            $logonType = ($data | Where-Object { $_.Name -eq 'LogonType' }).'#text'
            $targetUser = ($data | Where-Object { $_.Name -eq 'TargetUserName' }).'#text'
            $sourceIP = ($data | Where-Object { $_.Name -eq 'IpAddress' }).'#text'
            $sourcePort = ($data | Where-Object { $_.Name -eq 'IpPort' }).'#text'
            $targetDomain = ($data | Where-Object { $_.Name -eq 'TargetDomainName' }).'#text'

            $logonTypeName = switch ($logonType) {
                "2"  { "Interactive (local)" }
                "3"  { "Network (SMB/share)" }
                "4"  { "Batch" }
                "5"  { "Service" }
                "7"  { "Unlock" }
                "8"  { "NetworkCleartext" }
                "9"  { "NewCredentials" }
                "10" { "RemoteInteractive (RDP)" }
                "11" { "CachedInteractive" }
                default { "Type $logonType" }
            }

            # Skip SYSTEM and service accounts for readability
            if ($targetUser -notin @('SYSTEM', 'LOCAL SERVICE', 'NETWORK SERVICE', 'DWM-1', 'DWM-2', 'DWM-3', 'UMFD-0', 'UMFD-1', 'ANONYMOUS LOGON', '$') -and $targetUser -notmatch '\$$') {
                $loginEvents += [PSCustomObject]@{
                    EventType = "LOGIN_SUCCESS"
                    Time = $event.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
                    User = "$targetDomain\$targetUser"
                    LogonType = $logonTypeName
                    SourceIP = $sourceIP
                    SourcePort = $sourcePort
                    Status = "SUCCESS"
                    EventID = 4624
                }
            }
        }
        Write-Host "  [+] Successful logins found: $($loginEvents.Count)" -ForegroundColor Green
    } catch {
        Write-Host "  [?] Could not read successful login events (may need admin)" -ForegroundColor DarkYellow
    }

    # Failed logins (brute-force detection)
    $failedLogins = @()
    try {
        $failEvents = Get-WinEvent -FilterHashtable @{LogName='Security'; ID=4625; StartTime=$startDate} -MaxEvents 500 -ErrorAction SilentlyContinue
        foreach ($event in $failEvents) {
            $xml = [xml]$event.ToXml()
            $data = $xml.Event.EventData.Data
            $targetUser = ($data | Where-Object { $_.Name -eq 'TargetUserName' }).'#text'
            $sourceIP = ($data | Where-Object { $_.Name -eq 'IpAddress' }).'#text'
            $failReason = ($data | Where-Object { $_.Name -eq 'FailureReason' }).'#text'
            $status = ($data | Where-Object { $_.Name -eq 'Status' }).'#text'
            $subStatus = ($data | Where-Object { $_.Name -eq 'SubStatus' }).'#text'

            $statusMeaning = switch ($subStatus) {
                "0xC0000064" { "User does not exist" }
                "0xC000006A" { "Wrong password" }
                "0xC0000234" { "Account locked out" }
                "0xC0000072" { "Account disabled" }
                "0xC000006F" { "Outside allowed hours" }
                "0xC0000070" { "Unauthorized workstation" }
                "0xC0000071" { "Password expired" }
                "0xC0000193" { "Account expired" }
                default { $subStatus }
            }

            $failedLogins += [PSCustomObject]@{
                EventType = "LOGIN_FAILED"
                Time = $event.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
                User = $targetUser
                LogonType = "Failed"
                SourceIP = $sourceIP
                SourcePort = ""
                Status = $statusMeaning
                EventID = 4625
            }
        }

        if ($failedLogins.Count -gt 0) {
            Write-Host "  [!] FAILED login attempts: $($failedLogins.Count)" -ForegroundColor Red

            # Group by source IP for brute-force detection
            $byIP = $failedLogins | Group-Object SourceIP | Sort-Object Count -Descending
            foreach ($group in $byIP | Select-Object -First 10) {
                $severity = if ($group.Count -ge 10) { "BRUTE-FORCE SUSPECTED" } elseif ($group.Count -ge 5) { "Suspicious" } else { "Normal" }
                $color = if ($group.Count -ge 10) { "Red" } elseif ($group.Count -ge 5) { "Yellow" } else { "White" }
                Write-Host "    From $($group.Name): $($group.Count) failures [$severity]" -ForegroundColor $color
            }

            # Group by target user
            $byUser = $failedLogins | Group-Object User | Sort-Object Count -Descending
            Write-Host "`n  [*] Targeted usernames:" -ForegroundColor Yellow
            foreach ($group in $byUser | Select-Object -First 10) {
                Write-Host "    '$($group.Name)': $($group.Count) attempts" -ForegroundColor DarkYellow
            }
        } else {
            Write-Host "  [OK] No failed login attempts in last 7 days" -ForegroundColor Green
        }

        $loginEvents += $failedLogins
    } catch {
        Write-Host "  [?] Could not read failed login events (may need admin)" -ForegroundColor DarkYellow
    }

    $loginEvents | Export-Csv "$REPORT_DIR\05_login_attempts.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "[+] Saved: 05_login_attempts.csv" -ForegroundColor DarkGreen

    return $loginEvents
}

# ============================================================================
# 6. SMB/SHARE ACCESS LOGGING
# ============================================================================

function Get-ShareAccessLog {
    Write-Host "`n[6/8] SHARE ACCESS & NETWORK USER ACTIVITY" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $accessLog = @()

    # Current SMB sessions (who is connected to our shares right now)
    Write-Host "[*] Checking active SMB sessions..." -ForegroundColor Yellow
    try {
        $sessions = Get-SmbSession -ErrorAction SilentlyContinue
        foreach ($session in $sessions) {
            $accessLog += [PSCustomObject]@{
                Type = "ACTIVE_SMB_SESSION"
                User = $session.ClientUserName
                SourceIP = $session.ClientComputerName
                Resource = "SMB Session"
                AccessTime = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
                Details = "Connected for $([math]::Round($session.SecondsExists/60,1)) minutes"
            }
            Write-Host "  [!] Active session: $($session.ClientUserName) from $($session.ClientComputerName)" -ForegroundColor Yellow
        }
        if ($sessions.Count -eq 0) {
            Write-Host "  [OK] No active SMB sessions" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [?] Could not check SMB sessions" -ForegroundColor DarkYellow
    }

    # Current open files on shares
    try {
        $openFiles = Get-SmbOpenFile -ErrorAction SilentlyContinue
        foreach ($file in $openFiles) {
            $accessLog += [PSCustomObject]@{
                Type = "OPEN_FILE"
                User = $file.ClientUserName
                SourceIP = $file.ClientComputerName
                Resource = $file.Path
                AccessTime = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
                Details = "File currently open"
            }
            Write-Host "  [!] Open file: $($file.ClientUserName) -> $($file.Path)" -ForegroundColor Yellow
        }
    } catch {}

    # Check for mapped network drives
    Write-Host "[*] Checking mapped network drives..." -ForegroundColor Yellow
    $netDrives = Get-PSDrive -PSProvider FileSystem | Where-Object { $_.DisplayRoot -like '\\*' }
    foreach ($drive in $netDrives) {
        $accessLog += [PSCustomObject]@{
            Type = "MAPPED_DRIVE"
            User = $env:USERNAME
            SourceIP = "localhost"
            Resource = "$($drive.Name): -> $($drive.DisplayRoot)"
            AccessTime = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
            Details = "Mapped network drive"
        }
        Write-Host "  [*] Mapped: $($drive.Name): -> $($drive.DisplayRoot)" -ForegroundColor Cyan
    }

    $accessLog | Export-Csv "$REPORT_DIR\06_share_access.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "[+] Saved: 06_share_access.csv" -ForegroundColor DarkGreen

    return $accessLog
}

# ============================================================================
# 7. WIFI & SAVED CREDENTIAL AUDIT
# ============================================================================

function Get-WiFiAudit {
    Write-Host "`n[7/8] WIFI & CREDENTIAL AUDIT" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $wifiData = @()

    # Saved WiFi profiles
    Write-Host "[*] Enumerating saved WiFi profiles..." -ForegroundColor Yellow
    try {
        $profiles = netsh wlan show profiles 2>&1
        $profileNames = $profiles | Select-String "All User Profile\s+:\s+(.+)" | ForEach-Object { $_.Matches.Groups[1].Value.Trim() }

        foreach ($name in $profileNames) {
            $details = netsh wlan show profile name="$name" key=clear 2>&1
            $auth = ($details | Select-String "Authentication\s+:\s+(.+)" | Select-Object -First 1 | ForEach-Object { $_.Matches.Groups[1].Value.Trim() })
            $cipher = ($details | Select-String "Cipher\s+:\s+(.+)" | Select-Object -First 1 | ForEach-Object { $_.Matches.Groups[1].Value.Trim() })
            $key = ($details | Select-String "Key Content\s+:\s+(.+)" | ForEach-Object { $_.Matches.Groups[1].Value.Trim() })

            $risk = if ($auth -match "Open") { "CRITICAL" }
                    elseif ($auth -match "WEP") { "CRITICAL" }
                    elseif ($auth -match "WPA-Personal" -and $cipher -match "TKIP") { "HIGH" }
                    elseif ($key -and $key.Length -lt 10) { "HIGH" }
                    else { "LOW" }

            $wifiData += [PSCustomObject]@{
                ProfileName = $name
                Authentication = $auth
                Cipher = $cipher
                Password = if ($key) { $key } else { "(not stored)" }
                PasswordLength = if ($key) { $key.Length } else { 0 }
                Risk = $risk
            }

            $color = switch ($risk) { "CRITICAL" { "Red" } "HIGH" { "DarkYellow" } default { "Green" } }
            $masked = if ($key) { $key.Substring(0, [Math]::Min(3, $key.Length)) + "***" } else { "N/A" }
            Write-Host "  [$risk] $name (Auth: $auth, Key: $masked)" -ForegroundColor $color
        }
    } catch {
        Write-Host "  [?] Could not enumerate WiFi profiles" -ForegroundColor DarkYellow
    }

    $wifiData | Export-Csv "$REPORT_DIR\07_wifi_audit.csv" -NoTypeInformation -Encoding UTF8
    Write-Host "[+] Saved: 07_wifi_audit.csv" -ForegroundColor DarkGreen

    return $wifiData
}

# ============================================================================
# 8. GENERATE HUMAN-READABLE REPORT
# ============================================================================

function New-ReadableReport {
    param(
        [array]$Hosts,
        [array]$OpenPorts,
        [array]$Weakpoints,
        [array]$Connections,
        [array]$LoginEvents,
        [array]$ShareAccess,
        [array]$WiFiAudit
    )

    Write-Host "`n[8/8] GENERATING READABLE REPORT" -ForegroundColor Cyan
    Write-Host "=" * 60 -ForegroundColor DarkGray

    $critCount = ($Weakpoints | Where-Object { $_.Severity -eq "CRITICAL" }).Count
    $highCount = ($Weakpoints | Where-Object { $_.Severity -eq "HIGH" }).Count
    $failedLogins = ($LoginEvents | Where-Object { $_.EventType -eq "LOGIN_FAILED" }).Count
    $successLogins = ($LoginEvents | Where-Object { $_.EventType -eq "LOGIN_SUCCESS" }).Count

    $report = @"
================================================================================
         LOOTING LARRY - NETWORK SECURITY REPORT
         Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
         Host: $env:COMPUTERNAME ($((Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -like '10.0.0.*' }).IPAddress))
         Scanner: PowerShell Native (NordVPN Bypass Mode)
================================================================================

╔══════════════════════════════════════════════════════════════════════════════╗
║                           EXECUTIVE SUMMARY                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  Hosts Discovered:        $($Hosts.Count.ToString().PadRight(50))║
║  Open Ports Found:        $($OpenPorts.Count.ToString().PadRight(50))║
║  Security Weakpoints:     $($Weakpoints.Count.ToString().PadRight(50))║
║    > CRITICAL:            $($critCount.ToString().PadRight(50))║
║    > HIGH:                $($highCount.ToString().PadRight(50))║
║  Failed Login Attempts:   $($failedLogins.ToString().PadRight(50))║
║  Successful Logins:       $($successLogins.ToString().PadRight(50))║
║  Active Connections:      $(($Connections | Where-Object { $_.State -eq 'Established' }).Count.ToString().PadRight(50))║
║  WiFi Profiles Saved:     $($WiFiAudit.Count.ToString().PadRight(50))║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

================================================================================
SECTION 1: DISCOVERED HOSTS ($($Hosts.Count) found)
================================================================================

"@

    foreach ($h in $Hosts) {
        $hostPorts = ($OpenPorts | Where-Object { $_.IP -eq $h.IP })
        $portList = ($hostPorts | ForEach-Object { "$($_.Port)/$($_.Service)" }) -join ", "
        $report += "  $($h.IP.PadRight(18)) MAC: $($h.MAC.PadRight(20)) Host: $($h.Hostname)`n"
        if ($portList) {
            $report += "                     Open Ports: $portList`n"
        }
        $report += "`n"
    }

    $report += @"

================================================================================
SECTION 2: OPEN PORTS - DETAILED ($($OpenPorts.Count) found)
================================================================================

"@

    foreach ($p in ($OpenPorts | Sort-Object Risk, IP)) {
        $riskTag = switch ($p.Risk) { "CRITICAL" { "[!!!]" } "HIGH" { "[!! ]" } "MEDIUM" { "[ ! ]" } default { "[ OK]" } }
        $report += "  $riskTag $($p.IP.PadRight(18)):$($p.Port.ToString().PadRight(8)) $($p.Service.PadRight(18)) Risk: $($p.Risk)`n"
        if ($p.Banner) {
            $report += "        Banner: $($p.Banner.Substring(0, [Math]::Min(60, $p.Banner.Length)))`n"
        }
    }

    $report += @"

================================================================================
SECTION 3: SECURITY WEAKPOINTS ($($Weakpoints.Count) found)
================================================================================

"@

    $wpNum = 1
    foreach ($wp in ($Weakpoints | Sort-Object @{Expression={switch ($_.Severity) { "CRITICAL" {0} "HIGH" {1} "MEDIUM" {2} default {3} }}})) {
        $report += @"
  [$wpNum] $($wp.Severity) - $($wp.Category)
      Host:        $($wp.Host) ($($wp.Hostname))
      Port:        $($wp.Port) ($($wp.Service))
      Finding:     $($wp.Finding)
      Fix:         $($wp.Remediation)

"@
        $wpNum++
    }

    $report += @"

================================================================================
SECTION 4: NETWORK CONNECTIONS ($(($Connections | Where-Object { $_.State -eq 'Established' }).Count) active)
================================================================================

  --- INBOUND (potential entry attempts) ---

"@

    $inbound = $Connections | Where-Object { $_.Direction -eq "INBOUND" -and $_.State -eq "Established" }
    if ($inbound.Count -eq 0) {
        $report += "  (none detected)`n"
    } else {
        foreach ($ib in $inbound) {
            $report += "  <- $($ib.RemoteAddress):$($ib.RemotePort) -> localhost:$($ib.LocalPort) [$($ib.Process)] $($ib.RemoteHostname)`n"
        }
    }

    $report += "`n  --- LISTENING SERVICES ---`n`n"
    $listeners = $Connections | Where-Object { $_.State -eq "Listen" } | Sort-Object LocalPort -Unique
    foreach ($l in $listeners) {
        $bindNote = if ($l.LocalAddress -eq "0.0.0.0" -or $l.LocalAddress -eq "::") { "ALL INTERFACES" } else { $l.LocalAddress }
        $report += "  :$($l.LocalPort.ToString().PadRight(8)) [$($l.Process.PadRight(20))] bound to $bindNote`n"
    }

    $report += @"

================================================================================
SECTION 5: LOGIN ATTEMPTS (Last 7 Days)
================================================================================

  Successful Logins: $successLogins
  Failed Logins:     $failedLogins

"@

    if ($failedLogins -gt 0) {
        $report += "  --- FAILED LOGIN ATTEMPTS (potential attacks) ---`n`n"
        $byIP = $LoginEvents | Where-Object { $_.EventType -eq "LOGIN_FAILED" } | Group-Object SourceIP | Sort-Object Count -Descending
        foreach ($group in $byIP | Select-Object -First 15) {
            $tag = if ($group.Count -ge 10) { " <<< BRUTE-FORCE SUSPECTED" } elseif ($group.Count -ge 5) { " <<< Suspicious" } else { "" }
            $report += "    From $($group.Name): $($group.Count) failures$tag`n"
        }

        $report += "`n  --- TARGETED USERNAMES ---`n`n"
        $byUser = $LoginEvents | Where-Object { $_.EventType -eq "LOGIN_FAILED" } | Group-Object User | Sort-Object Count -Descending
        foreach ($group in $byUser | Select-Object -First 15) {
            $report += "    '$($group.Name)': $($group.Count) attempts`n"
        }
    }

    $report += @"

  --- RECENT SUCCESSFUL LOGINS ---

"@
    $recentSuccess = $LoginEvents | Where-Object { $_.EventType -eq "LOGIN_SUCCESS" } | Select-Object -First 20
    foreach ($login in $recentSuccess) {
        $report += "    $($login.Time)  $($login.User.PadRight(30))  $($login.LogonType.PadRight(25))  From: $($login.SourceIP)`n"
    }

    $report += @"

================================================================================
SECTION 6: WIFI SECURITY AUDIT ($($WiFiAudit.Count) profiles)
================================================================================

"@

    foreach ($wifi in $WiFiAudit) {
        $riskTag = switch ($wifi.Risk) { "CRITICAL" { "[!!!]" } "HIGH" { "[!! ]" } default { "[ OK]" } }
        $masked = if ($wifi.Password -ne "(not stored)") { $wifi.Password.Substring(0, [Math]::Min(3, $wifi.Password.Length)) + "***" + " (len:$($wifi.PasswordLength))" } else { "N/A" }
        $report += "  $riskTag $($wifi.ProfileName.PadRight(25)) Auth: $($wifi.Authentication.PadRight(15)) Cipher: $($wifi.Cipher.PadRight(8)) Key: $masked`n"
    }

    $report += @"

================================================================================
                          END OF REPORT
         Files saved to: $REPORT_DIR
         Review CSV files for full machine-readable data.
================================================================================
"@

    # Save report
    $reportPath = "$REPORT_DIR\SECURITY_REPORT.txt"
    $report | Out-File -FilePath $reportPath -Encoding UTF8
    Write-Host "[+] Full report saved: SECURITY_REPORT.txt" -ForegroundColor Green

    # Also save a JSON summary
    $summary = @{
        scan_time = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        hostname = $env:COMPUTERNAME
        local_ip = "10.0.0.100"
        hosts_found = $Hosts.Count
        open_ports = $OpenPorts.Count
        weakpoints_total = $Weakpoints.Count
        weakpoints_critical = $critCount
        weakpoints_high = $highCount
        failed_logins = $failedLogins
        successful_logins = $successLogins
        active_connections = ($Connections | Where-Object { $_.State -eq 'Established' }).Count
        wifi_profiles = $WiFiAudit.Count
        report_directory = $REPORT_DIR
        files = @(
            "01_discovered_hosts.csv"
            "02_open_ports.csv"
            "03_security_weakpoints.csv"
            "04_network_connections.csv"
            "05_login_attempts.csv"
            "06_share_access.csv"
            "07_wifi_audit.csv"
            "SECURITY_REPORT.txt"
        )
    } | ConvertTo-Json -Depth 3

    $summary | Out-File -FilePath "$REPORT_DIR\scan_summary.json" -Encoding UTF8
    Write-Host "[+] JSON summary saved: scan_summary.json" -ForegroundColor Green

    return $reportPath
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

Write-Banner
Write-Host "Starting full security scan at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor White
Write-Host "Network: 10.0.0.0/24 | Gateway: 10.0.0.138 | Local: 10.0.0.100" -ForegroundColor DarkGray
Write-Host ""

$hosts = Invoke-NetworkDiscovery
$openPorts = Invoke-PortScan -Hosts $hosts
$weakpoints = Invoke-WeakpointAnalysis -OpenPorts $openPorts -Hosts $hosts
$connections = Get-NetworkUsers
$loginEvents = Get-LoginAttempts
$shareAccess = Get-ShareAccessLog
$wifiAudit = Get-WiFiAudit
$reportPath = New-ReadableReport -Hosts $hosts -OpenPorts $openPorts -Weakpoints $weakpoints -Connections $connections -LoginEvents $loginEvents -ShareAccess $shareAccess -WiFiAudit $wifiAudit

Write-Host "`n" -NoNewline
Write-Host "╔═══════════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║                    SCAN COMPLETE - ALL 8 MODULES                      ║" -ForegroundColor Green
Write-Host "╠═══════════════════════════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "║  Results: $($REPORT_DIR.PadRight(60))║" -ForegroundColor Green
Write-Host "║  Report:  SECURITY_REPORT.txt                                        ║" -ForegroundColor Green
Write-Host "╚═══════════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
