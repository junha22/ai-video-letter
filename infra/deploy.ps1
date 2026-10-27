# 온기 Azure 리소스 만들기·바꾸기 (infra/main.bicep). docs/DEPLOY_AZURE.md '3. Azure 리소스 만들기'
# 사용: .\infra\deploy.ps1 -ResourceGroup rg-ongi-poc -Location koreacentral
#   비밀값은 infra/params.local.json (params.example.json을 복사, git에 올리지 않는다)
# 다시 실행하면 앱이 켜진 상태(replica 1)로 돌아간다. 꺼 두려면 이어서 .\infra\ops.ps1 stop
param(
    [Parameter(Mandatory = $true)] [string] $ResourceGroup,
    [string] $Location = "koreacentral",
    [string] $ParamsFile = (Join-Path $PSScriptRoot "params.local.json")
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $ParamsFile)) {
    throw "$ParamsFile 이 없습니다. infra\params.example.json을 복사해서 값을 채우세요."
}
az group create --name $ResourceGroup --location $Location --output none
if ($LASTEXITCODE -ne 0) { throw "리소스 그룹을 만들지 못했습니다 (지역 제한일 수 있습니다: docs/DEPLOY_AZURE.md 1단계)" }

az deployment group create `
    --resource-group $ResourceGroup `
    --template-file (Join-Path $PSScriptRoot "main.bicep") `
    --parameters "@$ParamsFile" `
    --parameters location=$Location `
    --query properties.outputs --output json
if ($LASTEXITCODE -ne 0) { throw "배포에 실패했습니다. 위 오류를 확인하세요." }
