# 시연·테스트 때만 켜기 (학생 크레딧 절약). docs/DEPLOY_AZURE.md '6. 시연 때 켜고 끄기'
#   .\infra\ops.ps1 start  -ResourceGroup rg-ongi-poc   Postgres 시작 → 앱 3개를 1개씩 켠다 (몇 분 걸림)
#   .\infra\ops.ps1 stop   -ResourceGroup rg-ongi-poc   앱을 0개로 줄이고 Postgres를 정지한다
#   .\infra\ops.ps1 status -ResourceGroup rg-ongi-poc
# Azure는 정지한 Postgres를 7일 뒤 자동으로 다시 켠다. 길게 안 쓸 때는 status로 확인하고 다시 stop
# GPU PC는 따로 켠다: npm run gpu + tailscale serve --bg 8200
param(
    [Parameter(Mandatory = $true, Position = 0)] [ValidateSet("start", "stop", "status")] [string] $Action,
    [Parameter(Mandatory = $true)] [string] $ResourceGroup,
    [string] $Prefix = "ongi"
)
$ErrorActionPreference = "Stop"

$apps = @("$Prefix-api", "$Prefix-worker", "$Prefix-web")
$pg = az postgres flexible-server list --resource-group $ResourceGroup --query "[0].name" --output tsv
if (-not $pg) { throw "$ResourceGroup 에 Postgres 서버가 없습니다. 먼저 infra\deploy.ps1" }

function Show-Status {
    $state = az postgres flexible-server show --resource-group $ResourceGroup --name $pg --query state --output tsv
    Write-Host "Postgres $pg : $state"
    foreach ($app in $apps) {
        $min = az containerapp show --resource-group $ResourceGroup --name $app --query "properties.template.scale.minReplicas" --output tsv
        $running = (az containerapp replica list --resource-group $ResourceGroup --name $app --query "length(@)" --output tsv 2>$null)
        Write-Host ("{0,-14} 최소 {1}개, 실행 중 {2}개" -f $app, $min, $running)
    }
    $fqdn = az containerapp show --resource-group $ResourceGroup --name "$Prefix-web" --query "properties.configuration.ingress.fqdn" --output tsv
    Write-Host "웹 주소: https://$fqdn"
}

switch ($Action) {
    "start" {
        $state = az postgres flexible-server show --resource-group $ResourceGroup --name $pg --query state --output tsv
        if ($state -ne "Ready") {
            Write-Host "Postgres 시작 중 ($state)..."
            az postgres flexible-server start --resource-group $ResourceGroup --name $pg --output none
        }
        # api·워커가 먼저 떠야 웹이 /api를 넘길 곳이 생긴다
        foreach ($app in $apps) {
            Write-Host "$app 켜는 중..."
            az containerapp update --resource-group $ResourceGroup --name $app --min-replicas 1 --output none
        }
        Show-Status
    }
    "stop" {
        foreach ($app in $apps) {
            Write-Host "$app 끄는 중..."
            az containerapp update --resource-group $ResourceGroup --name $app --min-replicas 0 --output none
        }
        $state = az postgres flexible-server show --resource-group $ResourceGroup --name $pg --query state --output tsv
        if ($state -eq "Ready") {
            Write-Host "Postgres 정지 중..."
            az postgres flexible-server stop --resource-group $ResourceGroup --name $pg --output none
        }
        Show-Status
    }
    "status" { Show-Status }
}
