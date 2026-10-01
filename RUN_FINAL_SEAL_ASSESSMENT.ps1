Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath 'C:\Users\12124\Documents\GitHub\Weekly-report-v2'

$reports = @(
    '.\.env.category-final-seal-round1.json',
    '.\.env.category-final-seal-round2.json',
    '.\.env.category-final-seal-round3.json'
)

$missing = $reports | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) {
    throw "Missing Final Seal report(s): $($missing -join ', ')"
}

python -B .\scripts\category_semantic_evaluation.py `
  --assess-round-reports `
  $reports[0] `
  $reports[1] `
  $reports[2]

if ($LASTEXITCODE -ne 0) {
    throw "Final Seal batch assessor exited with code $LASTEXITCODE"
}
