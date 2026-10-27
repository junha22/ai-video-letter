// 온기 시연용(PoC) Azure 구성. 자세한 순서는 docs/DEPLOY_AZURE.md
//   web    : Next.js (외부 공개). /api/*는 같은 환경의 api 앱으로 넘긴다 (BACKEND_URL은 이미지 빌드 때 http://<apiName>)
//   api    : FastAPI (내부 전용)
//   worker : 작업 워커 (항상 1개). TTS·영상 생성은 GPU PC 게이트웨이(Tailscale Funnel)를 부른다
//   Postgres(B1ms) + Azure Files(녹음·사진·영상, /data)
// 배포: infra/deploy.ps1 (az deployment group create). 이미지 교체는 GitHub Actions(.github/workflows/deploy.yml)가 한다
// 시연 때만 켜기: infra/ops.ps1 start|stop (이 파일을 다시 배포하면 아래 replica 수로 돌아간다)

@description('지역. 학생 구독은 허용 지역이 제한될 수 있다 (docs/DEPLOY_AZURE.md 1단계)')
param location string = resourceGroup().location

@description('리소스 이름 앞부분')
param prefix string = 'ongi'

@description('백엔드 이미지 (API·워커 공용). 예: ghcr.io/junha22/ongi-backend:latest')
param backendImage string

@description('웹 이미지. BACKEND_URL=http://<prefix>-api로 빌드한 것')
param webImage string

@description('이미지 저장소 (GHCR)')
param registryServer string = 'ghcr.io'
param registryUsername string
@secure()
@description('GHCR 읽기 권한(read:packages) 토큰')
param registryPassword string

param postgresAdminUser string = 'ongiadmin'
@secure()
param postgresAdminPassword string

@secure()
@description('세션 쿠키 서명 키 (긴 임의 문자열)')
param sessionSecret string

@secure()
@description('HyperCLOVA X 키. 비우면 규칙 기반 기본 대본')
param naverApiKey string = ''

@description('GPU PC 게이트웨이 주소 (Tailscale Funnel). 예: https://my-pc.tail1234.ts.net')
param gpuGatewayUrl string
@secure()
@description('게이트웨이 토큰 (GPU PC backend/.env의 GPU_GATEWAY_TOKEN과 같은 값)')
param gpuGatewayToken string

@description('동의 화면에 보이는 저장·처리 장소 안내')
param dataProcessingNotice string = '목소리·사진·영상은 Microsoft Azure 클라우드에 저장되고, 음성과 영상은 연구팀 GPU 컴퓨터에서 만들어요.'
@description('동의 문구를 바꾸면 같이 바꾼다')
param consentVersion string = '2026-10-azure'

@description('처음 배포할 때 켜 둘지 (이후에는 infra/ops.ps1 start|stop)')
param running bool = true

var suffix = uniqueString(resourceGroup().id)
var apiName = '${prefix}-api'
var replicas = running ? 1 : 0

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 } // 무료 5GB/월을 넘지 않도록
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('${prefix}data${suffix}', 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'ongi-data'
  properties: { shareQuota: 50 }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: '${prefix}-db-${suffix}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'ongi'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Container Apps(사용량 과금 환경)는 고정 출구 IP가 없어서 Azure 내부 접속만 허용한다 (0.0.0.0 규칙)
resource postgresAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: env
  name: 'ongidata'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: share.name
      accessMode: 'ReadWrite'
    }
  }
}

var publicBaseUrl = 'https://${prefix}-web.${env.properties.defaultDomain}'
var databaseUrl = 'postgresql+psycopg://${postgresAdminUser}:${uriComponent(postgresAdminPassword)}@${postgres.properties.fullyQualifiedDomainName}:5432/ongi?sslmode=require'

// Container Apps는 빈 비밀값을 받지 않아서 HyperCLOVA 키는 있을 때만 넣는다
var naverSecret = empty(naverApiKey) ? [] : [ { name: 'naver-api-key', value: naverApiKey } ]
var naverEnv = empty(naverApiKey) ? [] : [ { name: 'NAVER_API_KEY', secretRef: 'naver-api-key' } ]

var backendSecrets = concat([
  { name: 'registry-password', value: registryPassword }
  { name: 'database-url', value: databaseUrl }
  { name: 'session-secret', value: sessionSecret }
  { name: 'gpu-token', value: gpuGatewayToken }
], naverSecret)

var backendEnv = concat(naverEnv, [
  { name: 'DATABASE_URL', secretRef: 'database-url' }
  { name: 'SESSION_SECRET', secretRef: 'session-secret' }
  { name: 'PUBLIC_BASE_URL', value: publicBaseUrl }
  { name: 'DATA_DIR', value: '/data' }
  { name: 'DEV_LOGIN', value: 'false' }
  { name: 'TTS_PROVIDER', value: 'wemeet' }
  { name: 'WEMEET_TTS_URL', value: '${gpuGatewayUrl}/tts' }
  { name: 'WEMEET_TTS_API_KEY', secretRef: 'gpu-token' }
  { name: 'VIDEO_PROVIDER', value: 'runpod' }
  { name: 'RUNPOD_VIDEO_ENDPOINT_ID', value: '${gpuGatewayUrl}/video' }
  { name: 'RUNPOD_API_KEY', secretRef: 'gpu-token' }
  // 음색 학습은 워커가 같은 기계에서 GPU로 돌리는 구조라 클라우드 워커에서는 끈다
  { name: 'S3GEN_TRAINING', value: 'false' }
  { name: 'VOICE_TARGET_SECONDS', value: '135' }
  { name: 'CONSENT_VERSION', value: consentVersion }
  { name: 'DATA_PROCESSING_NOTICE', value: dataProcessingNotice }
])

var registries = [
  { server: registryServer, username: registryUsername, passwordSecretRef: 'registry-password' }
]

// 이미지의 사용자(uid 10001)가 Azure Files에 쓸 수 있게 한다
var dataVolume = {
  name: 'data'
  storageType: 'AzureFile'
  storageName: envStorage.name
  mountOptions: 'uid=10001,gid=10001,dir_mode=0750,file_mode=0640'
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-web'
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: { external: true, targetPort: 3000, transport: 'auto', allowInsecure: false }
      registries: registries
      secrets: [ { name: 'registry-password', value: registryPassword } ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
        }
      ]
      scale: { minReplicas: replicas, maxReplicas: 2 }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiName
  location: location
  dependsOn: [ postgresDb, postgresAllowAzure ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      // 내부 전용: 브라우저는 web을 거쳐서만 들어온다 (세션 쿠키·출처 검사가 web 주소 기준)
      ingress: { external: false, targetPort: 8000, transport: 'auto', allowInsecure: true }
      registries: registries
      secrets: backendSecrets
    }
    template: {
      containers: [
        {
          name: 'api'
          image: backendImage
          env: backendEnv
          resources: { cpu: json('0.5'), memory: '1Gi' }
          volumeMounts: [ { volumeName: 'data', mountPath: '/data' } ]
          probes: [
            { type: 'Readiness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 30, timeoutSeconds: 10 }
          ]
        }
      ]
      volumes: [ dataVolume ]
      scale: { minReplicas: replicas, maxReplicas: 1 }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-worker'
  location: location
  dependsOn: [ postgresDb, postgresAllowAzure ]
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      registries: registries
      secrets: backendSecrets
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: backendImage
          command: [ 'python', '-m', 'app.worker' ]
          env: backendEnv
          // 영상 합성(ffmpeg)·자막을 CPU로 한다
          resources: { cpu: json('1.0'), memory: '2Gi' }
          volumeMounts: [ { volumeName: 'data', mountPath: '/data' } ]
        }
      ]
      volumes: [ dataVolume ]
      // 작업 큐는 워커 1개를 전제로 한다 (README '작업 큐')
      scale: { minReplicas: replicas, maxReplicas: 1 }
    }
  }
}

output webUrl string = publicBaseUrl
output postgresServer string = postgres.name
output storageAccount string = storage.name
output apiAppName string = api.name
output workerAppName string = worker.name
output webAppName string = web.name
