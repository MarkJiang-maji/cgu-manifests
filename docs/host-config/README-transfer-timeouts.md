# 傳輸逾時修正（2026-11-26，先在 .6 上線）

給：負責 cgu-manifests 和 .4 / .6 部署的人。

## 問題

使用者反映：上傳、下載大檔，或連線安靜一段時間，就會被踢掉。實測找到三個原因：

| 原因 | 位置 | 症狀 |
|---|---|---|
| nginx 沒設逾時，用預設 60 秒 | .6 主機 `/etc/nginx/sites-enabled/kf` | 伺服器 60 秒沒回應就 504；Jupyter kernel / VNC 這類 websocket 安靜 60 秒就斷 |
| nginx `client_max_body_size 512M` | 同上 | 上傳超過 512 MB 直接回 413 |
| PVCViewer 路由 `timeout: 30s`（Kubeflow 預設） | `apps/volumes-web-app/upstream/base/viewer-spec.yaml` | 經由 PVCViewer 下載超過約 1 GB 的檔案，30 秒後被切斷，檔案不完整 |

## 改法

1. nginx（不在 kustomize 裡，這裡放一份副本：[nginx-kflow2-kf.conf](nginx-kflow2-kf.conf)）。兩個 server 區塊都改成：
   ```
   client_max_body_size 5G;
   proxy_read_timeout 3600s;
   proxy_send_timeout 3600s;
   ```
   - 這兩個逾時算的是「兩次收到資料之間的間隔」，不是總時間。只要一直有資料在傳就不會斷，安靜超過 1 小時才斷。
   - 上傳上限 5G 對所有人都一樣，因為 nginx 在登入檢查前面，不知道使用者是誰。
2. `viewer-spec.yaml` 的 `timeout: 30s` 改成 `0s`，也就是不限總時間。
   - ConfigMap 是用 subPath 掛進 volumes-web-app 的，改完一定要重啟 `volumes-web-app-deployment`，新設定才會生效。
   - 這個值只影響之後新建的 viewer。已經存在的 PVCViewer 要另外 patch。controller 只會更新 VirtualService，viewer 的 pod 不會重啟：
     ```
     kubectl -n <ns> patch pvcviewer <name> --type merge -p '{"spec":{"networking":{"timeout":"0s"}}}'
     ```

Istio 閘道本身沒有閒置逾時（Envoy `stream_idle_timeout: 0s`），所以後面不需要再改。

## 套到 .4 時

- 先比對 .4 的 nginx 設定和 PVCViewer 數量，不要直接複製 .6 的 kf 檔。kf 裡有 .6 自己的 server_name 和憑證路徑。
- 照上面三步做，再跑一次實測。.6 的實測腳本和結果在 .6 的 `/home/mark/idle-timeout-fix-20261126/`。
