# The same vRO action as powered_off_vms.ts, written with PowerCLI.
# Windmill installs the module from the PowerShell Gallery on first run and caches it.
# Runs on Linux workers (pwsh) and on native Windows workers.

param(
    [PSCustomObject]$Vsphere,
    [string]$Prefix = ""
)

Import-Module VMware.VimAutomation.Core
Set-PowerCLIConfiguration -Scope Session -ParticipateInCEIP $false -InvalidCertificateAction Warn -Confirm:$false | Out-Null

$cred = New-Object System.Management.Automation.PSCredential(
    $Vsphere.user, (ConvertTo-SecureString $Vsphere.password -AsPlainText -Force))
$server = Connect-VIServer -Server $Vsphere.server -Credential $cred

try {
    $vms = Get-VM -Server $server -Name "$Prefix*" |
        Where-Object { $_.PowerState -eq 'PoweredOff' } |
        Select-Object Name, NumCpu, MemoryGB, @{ n = 'Id'; e = { $_.ExtensionData.MoRef.Value } }
    Write-Host "Found $(@($vms).Count) powered-off VMs"
    $vms | ConvertTo-Json -AsArray
}
finally {
    Disconnect-VIServer -Server $server -Confirm:$false
}
