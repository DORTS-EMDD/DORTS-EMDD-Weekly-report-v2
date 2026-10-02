Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$evaluationScript = Join-Path $repositoryRoot 'scripts\category_semantic_evaluation.py'
$evidenceDirectory = Join-Path $repositoryRoot 'docs\category-v4-final-seal'

$reports = @(
    (Join-Path $evidenceDirectory 'category-final-seal-round1.json'),
    (Join-Path $evidenceDirectory 'category-final-seal-round2.json'),
    (Join-Path $evidenceDirectory 'category-final-seal-round3.json')
)

$missing = $reports | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) {
    throw "Missing Final Seal report(s): $($missing -join ', ')"
}

python -B $evaluationScript `
  --assess-round-reports `
  $reports[0] `
  $reports[1] `
  $reports[2]

if ($LASTEXITCODE -ne 0) {
    throw "Final Seal batch assessor exited with code $LASTEXITCODE"
}
