# CSV 統計 CLI 工具 - 測試報告

## 概述

本報告針對 `csv_stats.py` 的功能進行驗證，確保其在六種特定情況下行為正確。測試案例涵蓋：

1. 正常資料
2. 負金額
3. 僅有標頭
4. 缺少欄位
5. 空白分類
6. 非法金額

測試工具為 `test_acceptance.py`，根據協議要求，該腳本需能獨立運行並與上游 B 版本（SHA: 247fcc73c270e4689f57bfb0fc13cd3fc8f9ea88）互動。

## 驗證流程

使用 `subprocess` 執行 `csv_stats.py`，並比對標準輸出與標準錯誤輸出。

## 測試案例詳解

### 1. 正常資料

- **命令**：`python csv_stats.py test_normal.csv`
- **輸入內容**：
  ```csv
  category,amount
  食品,100.00
  交通,100.25
  食品,50.00
  ```
- **預期輸出**：
  ```json
  {
    "total_count": 3,
    "total_amount": "250.25",
    "category_stats": {
      "食品": {"count": 2, "amount": "150.00"},
      "交通": {"count": 1, "amount": "100.25"}
    }
  }
  ```
- **覆蓋需求**：正常資料處理、分類統計、金額加總

### 2. 負金額

- **命令**：`python csv_stats.py test_negative.csv`
- **輸入內容**：
  ```csv
  category,amount
  食品,-50.00
  交通,100.25
  ```
- **預期輸出**：
  ```json
  {
    "total_count": 2,
    "total_amount": "50.25",
    "category_stats": {
      "食品": {"count": 1, "amount": "-50.00"},
      "交通": {"count": 1, "amount": "100.25"}
    }
  }
  ```
- **覆蓋需求**：負金額正確計算

### 3. 僅有標頭

- **命令**：`python csv_stats.py test_header_only.csv`
- **輸入內容**：
  ```csv
  category,amount
  ```
- **預期輸出**：
  ```json
  {
    "total_count": 0,
    "total_amount": "0.00",
    "category_stats": {}
  }
  ```
- **覆蓋需求**：空文件處理

### 4. 缺少欄位

- **命令**：`python csv_stats.py test_missing_field.csv`
- **輸入內容**：
  ```csv
  category
  食品
  ```
- **預期錯誤訊息**：`錯誤：CSV 檔案缺少必要欄位。`
- **退出碼**：1
- **覆蓋需求**：欄位缺失錯誤處理

### 5. 空白分類

- **命令**：`python csv_stats.py test_empty_category.csv`
- **輸入內容**：
  ```csv
  category,amount
  食品,100.00
  ,50.00
  ```
- **預期輸出**：
  ```json
  {
    "total_count": 2,
    "total_amount": "150.00",
    "category_stats": {
      "食品": {"count": 1, "amount": "100.00"},
      "UNKNOWN": {"count": 1, "amount": "50.00"}
    }
  }
  ```
- **覆蓋需求**：空白分類轉換為 UNKNOWN

### 6. 非法金額

- **命令**：`python csv_stats.py test_invalid_amount.csv`
- **輸入內容**：
  ```csv
  category,amount
  食品,abc
  ```
- **預期錯誤訊息**：`錯誤：金額格式無效。`
- **退出碼**：1
- **覆蓋需求**：非法金額錯誤處理

## 運行方式

```bash
python3 -m unittest -v test_acceptance
```

## 驗證結果

所有測試案例均已通過，未發現任何失敗或錯誤。B 版本的 `test_csv_stats.py` 也保持通過。
