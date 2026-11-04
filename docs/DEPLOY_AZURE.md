# Azure 배포 (시연용 PoC)

Azure for Students 구독으로 웹·API·워커·DB·파일은 Azure에, GPU 작업(TTS·영상)은 연구실 GPU PC에 둔다.
시연·테스트 때만 켜서 크레딧을 아낀다. 음색 학습(S3Gen)은 Azure 워커가 GPU PC의 학습 서버에 녹음을 보내 맡긴다 (워커에 GPU가 없어서).

```
[휴대폰·PC 브라우저] ──HTTPS──> Azure Container Apps
                                ├ ongi-web     Next.js (외부 공개). /api/* → ongi-api
                                ├ ongi-api     FastAPI (내부 전용)
                                └ ongi-worker  작업 워커 (1개)
                                     │                 │
                          PostgreSQL B1ms        Azure Files (/data: 녹음·사진·영상)
           (api·worker 옆 Tailscale 컨테이너, 프록시 127.0.0.1:1055)
                                     │
                       tailnet 안 HTTPS (tailscale serve) + 토큰 · 공개 주소 없음
                                     │
                      [GPU PC]  gpu_worker/gateway.py :8200
                                  ├ /tts   → TTS 서버 :8100
                                  ├ /video → 영상 서버(FLOAT) :8010
                                  └ /train → 음색 학습 서버 :8300 (gpu_worker/trainer.py)
```

GPU PC가 꺼져 있으면 로그인·대화방·답글·이미 만든 영상 보기는 되고, 목소리 등록과 영상 생성만 실패한다.

| 파일 | 역할 |
|---|---|
| `backend/Dockerfile` | API·워커 이미지 (한글 글꼴 포함, GPU 코드 없음) |
| `Dockerfile.web` | 웹 이미지. `/api/*`는 `src/app/api/[...path]/route.ts`가 `BACKEND_URL`(실행할 때 읽음, 기본 `http://ongi-api`)로 넘긴다 |
| `infra/main.bicep` | Azure 리소스 전체 |
| `infra/deploy.ps1` | 리소스 만들기·바꾸기 |
| `infra/ops.ps1` | 시연 때 켜고 끄기 |
| `infra/params.example.json` | 비밀값 양식 → `infra/params.local.json`으로 복사 (git 제외) |
| `.github/workflows/deploy.yml` | main 푸시 → 테스트 → 이미지 빌드 → Azure 이미지 교체 |
| `backend/gpu_worker/gateway.py` | GPU PC의 TTS·영상·학습 서버를 주소 하나로 묶고 토큰으로 막는다 (`npm run gpu`) |
| `backend/gpu_worker/trainer.py` | GPU PC 음색 학습 서버. Azure 워커가 보낸 녹음으로 S3Gen 학습 → 비교 → 더 닮았을 때만 어댑터를 돌려준다 (녹음은 끝나면 지운다) |

## 1. 사전 확인 (로그인 필요)

Azure CLI: `%LOCALAPPDATA%\Programs\azure-cli` (PATH에 추가됨). 새 터미널에서:

```powershell
az login
az account show --query "{구독:name, 종류:subscriptionPolicies.quotaId, 테넌트:tenantId, 사용자:user.name}"
# 허용 지역 정책 (학생 구독은 지역이 제한될 수 있다). 결과에 koreacentral이 있는지
az policy assignment list --query "[].{이름:displayName, 지역:parameters.listOfAllowedLocations.value}" -o json
# 쓰는 서비스 등록
foreach ($p in "Microsoft.App","Microsoft.OperationalInsights","Microsoft.DBforPostgreSQL","Microsoft.Storage") { az provider register -n $p }
# 이 지역에서 Postgres B1ms를 만들 수 있는지
az postgres flexible-server list-skus -l koreacentral --query "[].supportedServerEditions[?name=='Burstable'].supportedServerSkus[].name" -o tsv
```

- Korea Central을 못 쓰면 허용 지역 중 가까운 곳(예: japaneast)을 쓰고, 동의 화면 안내 문구(`dataProcessingNotice`)를 그 지역에 맞게 바꾼다.
- 크레딧 잔액은 https://www.microsoftazuresponsorships.com 에서 본다. Postgres B1ms가 무료 혜택(12개월, 월 750시간)에 들어가는지도 확인한다.
- 예산 알림: 포털 → 비용 관리 → 예산 ($50, $80). 학생 구독은 지원하지 않을 수 있다.

## 2. GPU PC 준비

1. `backend/.env`에 `GPU_GATEWAY_TOKEN`(24자 이상 임의 문자열)이 있는지 확인한다. 같은 값을 Azure `gpuGatewayToken`에 넣는다.
2. Tailscale 설치·로그인(개인 계정) → 관리 화면(https://login.tailscale.com/admin) **DNS**에서 MagicDNS와 **HTTPS 인증서**를 켠다. PC 이름을 `ongi-gpu`처럼 정한다.
3. 관리 화면 **Settings → Keys → Generate auth key**: **Reusable**와 **Ephemeral**을 켜고 만든다 (`tskey-auth-…`).
   `infra/params.local.json`의 `tailscaleAuthKey`에 넣는다. Azure의 api·worker 옆 Tailscale 컨테이너가 이 키로 tailnet에 들어온다 (꺼지면 자동으로 빠짐). 키 유효 기간이 지나면 새로 만들어 다시 배포한다.
4. GPU 서버와 게이트웨이를 띄우고 tailnet 안에만 연다.
   ```powershell
   conda activate ai-video-letter
   npm run gpu                      # TTS·영상 서버 + 음색 학습 서버 :8300 + 게이트웨이 :8200 (창을 닫으면 같이 꺼진다)
   tailscale serve --bg 8200        # 다른 창에서. tailnet 안에서만 https://<PC>.<tailnet>.ts.net
   ```
5. 전원 옵션에서 절전·최대 절전을 끈다.

공개 주소를 여는 **Funnel은 쓰지 않는다.** Funnel 주소가 공개 DNS에 등록되지 않아 Azure에서 찾지 못한 적이 있고 (2026-10-27), tailnet 안에서만 열면 GPU 서버가 인터넷에 드러나지 않는다.

게이트웨이는 `/health`와 `/tts/health`만 토큰 없이 열고, 나머지는 `X-API-Key` 또는 `Authorization: Bearer` 토큰을 확인한다. 음성·사진·영상 내용은 로그에 남기지 않는다.

## 3. 이미지 만들기

main에 푸시하면 GitHub Actions가 테스트(SQLite·PostgreSQL) 후 이미지를 GHCR에 올린다.

- `ghcr.io/<저장소 주인>/ongi-backend:<커밋>` / `:latest`
- `ghcr.io/<저장소 주인>/ongi-web:<커밋>` / `:latest` (`BACKEND_URL=http://ongi-api`)

저장소가 공개라 이미지도 공개로 올라간다 (로그인 없이 받을 수 있음). 그래서 `registryUsername`·`registryPassword`는 비워 둔다.
이미지에는 저장소에 이미 공개된 코드만 들어간다 (`.dockerignore`가 `.env`·데이터·모델을 뺀다).
저장소를 비공개로 바꾸면 GitHub **classic 토큰(read:packages)**을 만들어 두 값을 채운다.

## 4. Azure 리소스 만들기

```powershell
Copy-Item infra\params.example.json infra\params.local.json   # 값 채우기 (git에 올라가지 않는다)
.\infra\deploy.ps1 -ResourceGroup rg-ongi-poc -Location koreacentral
```

출력의 `webUrl`이 사이트 주소다 (`https://ongi-web.<임의>.koreacentral.azurecontainerapps.io`). DB 테이블은 API가 처음 뜰 때 만들어진다.
`deploy.ps1`을 다시 실행하면 앱이 켜진 상태로 돌아간다. 꺼 두려면 이어서 `.\infra\ops.ps1 stop`.

## 5. GitHub Actions 자동 배포 연결

배포 단계는 아래 값이 있을 때만 돈다 (없으면 테스트·이미지 빌드까지만). 저장소 관리자가 설정한다.

```powershell
$rg = "rg-ongi-poc"; $repo = "junha22/ai-video-letter"
$app = az ad app create --display-name ongi-github-deploy --query appId -o tsv
az ad sp create --id $app
az ad app federated-credential create --id $app --parameters "{\"name\":\"main\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"repo:${repo}:ref:refs/heads/main\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
az role assignment create --assignee $app --role Contributor --scope (az group show -n $rg --query id -o tsv)
az account show --query "{AZURE_TENANT_ID:tenantId, AZURE_SUBSCRIPTION_ID:id}"; "AZURE_CLIENT_ID: $app"
```

- 저장소 Settings → Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`
- 저장소 Settings → Variables: `AZURE_RESOURCE_GROUP=rg-ongi-poc`
- 학교 계정 테넌트에서 앱 등록이 막혀 있으면 `az ad app create`가 실패한다. 그때는 4단계 `deploy.ps1`을 이미지 태그만 바꿔 다시 실행하는 수동 배포로 대신한다.
- main에 푸시하면 바로 시연 서버 이미지가 바뀐다. 시연 직전에는 푸시를 조심한다.

## 6. 시연 때 켜고 끄기

```powershell
.\infra\ops.ps1 start  -ResourceGroup rg-ongi-poc   # Postgres 시작 → 앱 켜기 (몇 분)
.\infra\ops.ps1 status -ResourceGroup rg-ongi-poc
.\infra\ops.ps1 stop   -ResourceGroup rg-ongi-poc   # 앱 0개, Postgres 정지
```

GPU PC는 따로 켠다 (2단계 3번). Azure는 정지한 Postgres를 7일 뒤 자동으로 다시 켜므로, 오래 안 쓸 때는 `status`로 확인하고 다시 `stop`한다.

## 7. 확인 목록 (휴대폰)

1. 웹 주소 접속 → 이메일 가입 → 동의 화면에 저장·처리 장소 안내가 보이는지
2. 대상자 등록 → 목소리 녹음 135초 → 등록 완료 (워커 로그: "TTS 목소리 등록")
3. 사진 등록 → 메시지 작성 → 대본 후보 → 영상 만들기 (생성 시간 기록)
4. 승인 → 링크 복사 → 다른 휴대폰에서 시청·답글 → 대화방에 답글이 보이는지
5. 로그(Log Analytics)에 공유 토큰(`/api/watch/***`)·대본 내용이 없는지

## 비용 (Korea Central 정가, USD)

| 항목 | 정가 | 메모 |
|---|---|---|
| Container Apps | vCPU $0.000024/초, 메모리 $0.000003/GiB·초 (사용 중) | 매달 무료분: vCPU 180,000초, 메모리 360,000GiB·초 |
| PostgreSQL B1ms | $0.026/시간 (켜 두면 월 약 $19) | 정지하면 저장 공간 비용만 |
| Azure Files | $0.03/GB·월 | |
| Log Analytics | 월 5GB 무료 | 하루 1GB 상한 설정 |
| 이미지 저장소 | GHCR 무료 | Azure Container Registry는 쓰지 않는다 |

## 주의

- 목소리·사진·영상이 Azure와 GPU PC에서 처리된다. 시연 참가자에게 동의 화면 안내(`DATA_PROCESSING_NOTICE`)로 알린다. 문구를 바꾸면 `consentVersion`도 바꾼다.
- FLOAT는 비상업 라이선스(CC BY-NC)라 시연·연구 용도로만 쓴다.
- GPU PC 주소는 tailnet 안에서만 열린다. Tailscale 인증 키나 게이트웨이 토큰이 새면 관리 화면에서 키를 지우고, `GPU_GATEWAY_TOKEN`과 Azure `gpuGatewayToken`도 함께 바꾼다.
- 연구용 음성(zoouzae 등)과 이 PC의 테스트 데이터는 클라우드에 올리지 않는다 (새 DB로 시작).

## 정리 (전부 삭제)

```powershell
az group delete --name rg-ongi-poc --yes
```
