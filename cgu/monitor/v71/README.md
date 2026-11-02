# CGU Monitor v71（計費 exporter）部署說明

v71 exporter 依每個使用者 namespace 的 CPU / GPU request 計算用量與費用，提供給 AI_Centre_Admin 前端（Home / User 頁）使用。
上一層的 `cgu/monitor/`（`prom.py`、`markjiang10/cgu-monitor:v53`）是舊版 v53；v71 不取代它，可以並存。

指標與設計說明見 [README_v2.md](README_v2.md)，與 v53 的數值比對見 [validation_v71.md](validation_v71.md)。

## 檔案

| 檔案 | 用途 |
|---|---|
| `prom_v2.py` | exporter 原始碼 |
| `kustomization.yaml` | 把下列資源組起來，並從 `prom_v2.py` 產生 ConfigMap `node-resource-monitor-script-v71` |
| `monitor-config.yaml` | 費率 ConfigMap `node-resource-monitor-config`（後端費率 API 需要） |
| `prom_v2.yaml` | 費率 ConfigMap、Deployment、Service（含 NodePort 30071）、ServiceAccount、RBAC |
| `prom_rules_v2.yaml` | recording rules，與 .6 線上相同 |
| `apply-prometheus-settings.sh` | 設定 Prometheus 的 NodePort 32049 與保留 360 天（.6 目前維持 180 天，不要在 .6 加 `CONFIRM_DATA_LOSS=yes` 執行） |
| `servicemonitor-v71.yaml` | 只有在**沒有** v53 的叢集才套用，見下方 |
| `kube-prom-stack-retention-180d.yaml` | .25 用過的 helm values。**.4、.6 不要用**：50Gi 放不下 180 天的資料，而且 Prometheus 官方不支援 NFS |
| `test_prom_v2.py` | 單元測試 |
| `validate_prom_v2.py` | 比對 v53 與 v71 `/metrics` 的工具 |
| `deploy-record-120.126.23.6.md` | 2026-05-13 部署到 .6 的紀錄 |

## 部署

前提：叢集已有 `cgu` namespace、kube-prometheus-stack（ServiceMonitor 需帶 `release: kube-prom-stack`）、Kubeflow `Profile` CRD。
Pod 啟動時會 `pip install` 套件，節點要能連到 PyPI。

在 repo 根目錄執行。先看差異，確認後才把 `kubectl diff` 換成 `kubectl apply`：

```bash
kustomize build cgu/monitor/v71 | python3 preserve_live_state.py | kubectl diff -f -
kustomize build cgu/monitor/v71 | python3 preserve_live_state.py | kubectl apply -f -
kubectl rollout status deploy/node-resource-monitor-v71 -n cgu --timeout=300s
bash cgu/monitor/v71/apply-prometheus-settings.sh
```

- 一定要經過 `preserve_live_state.py`，否則會把網頁上改過的費率蓋回初始值。
- 只動 v71，不動 v53。v71 啟動時要從 v53 載入累積費用，v53 要繼續跑。
- Prometheus 沒有 PVC 時，改保留天數會重建 pod 並清掉所有資料，腳本會先停下來；確認可接受後加 `CONFIRM_DATA_LOSS=yes` 再跑。
- 完整的 `apply.sh` 也會裝 v71（`cgu/monitor/kustomization.yaml` 已包含），但它還會動到其他元件，只更新 monitor 時不要用。

### 叢集上沒有 v53 時

1. Prometheus 抓不到 v71：v71 是靠 v53 的 ServiceMonitor（selector `app: prom-app`）被抓取的，要另外套用：

   ```bash
   kubectl apply -f servicemonitor-v71.yaml
   ```

   已經有 v53 的叢集（.6、.25）**不要**套用，否則會重複抓取。

2. `prom_v2.yaml` 的 `LEGACY_BOOTSTRAP_URL` 指向 v53 的 `prom-app`，用來在啟動時接續 v53 的累積費用。
   沒有 v53 時，exporter 仍會正常運作，累積值從 0 開始，但每分鐘會記一筆 warning。可以把它設成空字串關掉：

   ```yaml
   - name: LEGACY_BOOTSTRAP_URL
     value: ""
   ```

   注意：累積費用只存在記憶體裡。沒有 v53 可接續時，Pod 重啟後 `namespace_*_cost*` 會從 0 重新累積。

## 費率

`node-resource-monitor-config` 與 `node-resource-monitor-config-v71` 裡的 `CPU_COST_PER_MINUTE: "0.03"`、`GPU_COST_PER_MINUTE: "0.7"` 只是初始值，與 .6 線上設定相同。
上線後費率由 AI_Centre_Admin 管理介面修改（兩個 ConfigMap 會一起改）。
這兩個 ConfigMap 列在 `preserve_live_state.py` 的 `CREATE_ONLY`，已存在時不會被重新套用。直接 `kubectl apply -f prom_v2.yaml` 會繞過這層保護，不要這樣做。

ConfigMap 讀不到時，程式預設值同樣是 0.03 / 0.7（`prom_v2.py` 的 `DEFAULT_*_COST_PER_MINUTE`）。

## 驗證

```bash
kubectl get deploy,svc,pod -n cgu | grep -E 'node-resource-monitor-v71|prom-app-v71'
curl -s http://<node-ip>:30071/metrics | grep -E '^(cgu_monitor_build_info|namespace_(cpu|gpu)_cost_time)' | head
```

Prometheus 上應查得到 `up{service="prom-app-v71"} == 1`，以及 `namespace_cpu_cost_time{service="prom-app-v71"}`。

## 修改程式之後

ConfigMap 會從 `prom_v2.py` 自動產生，但更新它不會重啟 pod，要自己 restart：

```bash
python3 -m unittest test_prom_v2          # 需要 kubernetes==26.1.0、prometheus-client==0.20.0
kustomize build cgu/monitor/v71 | python3 preserve_live_state.py | kubectl apply -f -
kubectl rollout restart deploy/node-resource-monitor-v71 -n cgu
```

重啟 exporter 不會影響 Prometheus 裡的歷史資料，但 `namespace_*_cost*` 累積值存在記憶體裡，重啟後會從 v53 重新載入，數值會跳動。`cgu_namespace_billable_*` 不受影響。
