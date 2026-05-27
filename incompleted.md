# 待下次實作清單 (incompleted.md)

> 更新：2026-05-28。所有 incompleted 項目已完成或轉移至「已完成」。
> 目前無已知 🔴 Bug。

---

## 已完成（本次清空）

| 項目 | 說明 | 狀態 |
|---|---|---|
| `fetch_vkospi` 404 | 新增 Stooq CSV fallback（`^vkospi` / `vkospi.ko`） | ✅ |
| OECD CLI 過期標注 | 動態計算資料截止月份，圖表左上角 + caption 顯示 ⚠️ | ✅ |
| Tab F 三大法人各類股（BFIAMU） | 新增 `fetch_tw_sector_institutional_by_sector()`，F-3 加橫向條形圖 + 明細表格 | ✅ |
| README 更新 | fetchers 結構、`.env` 範例、資料來源更新（Eastmoney/MOFCOM/NDC/FinMind/Stooq） | ✅ |

---

## 🟡 長期觀察項

### OECD CLI 停更
- DBnomics OECD MEI 資料截止 2023-12，無法由 fetcher 端修復。
- 圖表已加 ⚠️ 標注，使用者看到後自行判斷。
- 若要升級：改接 `stats.oecd.org/sdmx-json`（OECD.Stat REST API），但格式複雜，低優先。

---

## 環境備忘（遠端）

- `root@10.1.1.230`：Yocto aarch64 (pico-imx8mm)，Docker，無 docker-compose。
- 容器 `macro-dashboard`（Python 3.11, pandas）：程式碼 `/app`，DB `/root/macro_dashboard_data`。
- 部署指令：`.\build_arm64.ps1 -Deploy`（本機 Windows PowerShell）
- 驗收：見 [remote_deploy.md](remote_deploy.md)
