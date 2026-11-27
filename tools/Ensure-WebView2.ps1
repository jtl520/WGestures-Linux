Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$key = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
foreach ($hive in @([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryHive]::CurrentUser)) {
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64)) {
        $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey($hive, $view)
        try {
            $runtime = $base.OpenSubKey($key)
            if ($runtime) {
                try {
                    $version = [string]$runtime.GetValue('pv')
                    if ($version -and $version -ne '0.0.0.0') { Write-Host "WebView2 runtime: $version"; return }
                } finally { $runtime.Dispose() }
            }
        } finally { $base.Dispose() }
    }
}
$bootstrapper = Join-Path ([IO.Path]::GetTempPath()) ('CrossGestures-WebView2-' + [Guid]::NewGuid().ToString('N') + '.exe')
try {
    Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrapper -UseBasicParsing
    $signature = Get-AuthenticodeSignature -LiteralPath $bootstrapper
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw 'WebView2 bootstrapper does not have a valid Microsoft signature.'
    }
    $process = Start-Process -FilePath $bootstrapper -ArgumentList '/silent', '/install' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "WebView2 installation failed: $($process.ExitCode)" }
} finally { Remove-Item -LiteralPath $bootstrapper -Force -ErrorAction SilentlyContinue }
