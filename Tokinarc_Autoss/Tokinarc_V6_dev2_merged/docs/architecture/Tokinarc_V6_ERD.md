# TOKINARC V6 — ERD Tổng thể (Entity Relationship Diagram)

> **Phiên bản**: V6.dev2 — sinh từ CODE THẬT (56 model, 9 app), 06/2026.
> Sơ đồ dùng Mermaid `erDiagram` — mở trên GitHub/VS Code để render.
> Bổ sung cho B.2 (chi tiết field) và LLD_DataFlow (luồng). Tài liệu này tập trung
> **quan hệ giữa các bảng**.

---

## Quy ước đọc

- **PK in đậm trong mô tả**: catalog dùng PK chuỗi (`tokin_part_no`, `model_code`),
  còn lại UUID7.
- **Audit FK dùng chung**: mọi model kế thừa `BaseModel` đều có
  `created_by / updated_by / deleted_by → User`. Để sơ đồ gọn, các FK audit này
  **KHÔNG vẽ** trong ERD — chỉ vẽ quan hệ nghiệp vụ. Xem §6 để biết danh sách.
- Ký hiệu Mermaid: `||--o{` = một-nhiều, `||--||` = một-một, `}o--||` = nhiều-một.
- `..` (nét đứt) = **loose key** (CharField chứa mã, không phải FK ràng buộc DB).

---

## 1. Bản đồ domain (toàn cảnh)

```mermaid
flowchart LR
    subgraph IDENT[Định danh]
        User
    end
    subgraph CAT[Catalog - PK chuỗi]
        Part
        Torch
    end
    subgraph CRMD[CRM]
        Customer
        Lead
        Opportunity
        Quote
        Ticket
        Visit
    end
    subgraph SALESD[Sales]
        SalesOrder
        Payment
    end
    subgraph WMSD[WMS]
        Warehouse
        InventoryItem
        SerialNumber
        OutboundOrder
        InboundOrder
    end
    subgraph LEARN[Learning]
        QueryLog
        GoldenExample
    end

    Lead -->|convert| Customer
    Customer --> Opportunity --> Quote
    Quote -.loose key.-> SalesOrder
    Customer --> SalesOrder --> Payment
    SalesOrder --> OutboundOrder
    Customer --> Ticket
    Customer --> Visit
    SalesOrder -.lines.-> Part & Torch
    Warehouse --> InventoryItem --> Part
    SerialNumber -.sold_to.-> Customer
    User -.owner/assignee.-> CRMD & SALESD
    QueryLog --> GoldenExample
```

---

## 2. CRM — quan hệ entity

```mermaid
erDiagram
    User ||--o{ Customer : owner
    User ||--o{ Lead : owner
    User ||--o{ Opportunity : owner
    User ||--o{ Quote : "owner / approved_by"
    User ||--o{ Visit : owner
    User ||--o{ Ticket : "created_owner / assignee"

    Lead }o--o| Customer : "converted_customer"
    Customer ||--o{ Contact : has
    Customer ||--o{ Opportunity : has
    Customer ||--o{ Quote : has
    Customer ||--o{ Visit : has
    Customer ||--o{ Ticket : has
    Opportunity ||--o{ Quote : "sinh ra"
    Quote ||--o{ QuoteLine : contains

    Customer {
        uuid id PK
        string code UK
        string name
        string segment
        string region
        string status
    }
    Lead {
        uuid id PK
        string name
        int score
        string status
        uuid converted_customer FK
    }
    Opportunity {
        uuid id PK
        uuid customer FK
        string stage
        decimal est_value_vnd
        int probability
    }
    Quote {
        uuid id PK
        string code UK
        uuid customer FK
        uuid opportunity FK
        string status
        decimal total_vnd
        string contract_order_code "loose→SalesOrder"
    }
    QuoteLine {
        uuid id PK
        uuid quote FK
        string part_no "loose→Part"
        int qty
        decimal unit_price_vnd
    }
    Ticket {
        uuid id PK
        string code UK
        uuid customer FK
        string status
        string priority
        string serial_no "loose→SerialNumber"
    }
    Visit {
        uuid id PK
        uuid customer FK
        date visit_date
    }
    Contact {
        uuid id PK
        uuid customer FK
        bool is_primary
    }
```

**Chú ý loose key** (nét `..` ở §1): `Quote.contract_order_code`, `QuoteLine.part_no`,
`Ticket.serial_no` là chuỗi mã, **không** FK — để tránh phụ thuộc cứng / circular import.

---

## 3. Sales + liên kết Catalog

```mermaid
erDiagram
    Customer ||--o{ SalesOrder : has
    User ||--o{ SalesOrder : owner
    SalesOrder ||--o{ SalesOrderLine : contains
    SalesOrder ||--o{ Payment : has
    SalesOrder }o--o| SalesOrder : "parent_order (hợp đồng khung)"
    SalesOrderLine }o--|| Part : references
    SalesOrderLine }o--o| Torch : references

    SalesOrder {
        uuid id PK
        string code UK
        uuid customer FK
        uuid parent_order FK
        string order_type
        string status
        string payment_terms
        decimal total_vnd
        decimal paid_vnd
    }
    SalesOrderLine {
        uuid id PK
        uuid order FK
        string part FK "→Part.tokin_part_no"
        string torch FK "→Torch.model_code"
        int qty
        decimal unit_price_vnd
    }
    Payment {
        uuid id PK
        uuid order FK
        decimal amount_vnd
        string method
        date paid_at
    }
    Part {
        string tokin_part_no PK
        string category
        string ecosystem
    }
    Torch {
        string model_code PK
        string family
    }
```

> Khác CRM: SalesOrderLine dùng **hard FK** tới Part/Torch (đơn bán cần ràng buộc
> toàn vẹn), trong khi QuoteLine dùng loose key (báo giá linh hoạt hơn).

---

## 4. WMS — kho, tồn, serial, nhập/xuất

```mermaid
erDiagram
    Warehouse ||--o{ Zone : has
    Zone ||--o{ Bin : has
    Bin ||--o{ InventoryItem : holds
    Bin ||--o{ Lot : holds
    InventoryItem }o--|| Part : "of part"
    InventoryItem }o--o| Torch : "of torch"
    Lot }o--|| Part : "of part"

    Warehouse ||--o{ ASN : receives
    ASN ||--o| InboundOrder : "→ tạo"
    InboundOrder ||--o{ InboundLine : contains
    InboundLine }o--|| Part : references
    InboundLine }o--o| Bin : target_bin

    Warehouse ||--o{ OutboundOrder : ships
    Customer ||--o{ OutboundOrder : "for"
    OutboundOrder ||--o{ OutboundLine : contains
    OutboundLine ||--o{ PickListItem : "picked as"
    PickListItem }o--o| Bin : from
    PickListItem }o--o| Lot : from
    PickListItem }o--o| SerialNumber : from

    SerialNumber }o--o| Torch : "of torch"
    SerialNumber }o--o| Bin : "at bin"
    SerialNumber }o--o| Customer : sold_to_customer
    Warehouse ||--o{ StockMovement : "sổ cái"

    Warehouse {
        uuid id PK
        string code UK
    }
    Bin {
        uuid id PK
        uuid zone FK
        string code
    }
    InventoryItem {
        uuid id PK
        uuid bin FK
        string part FK
        int qty_on_hand
        int qty_reserved
    }
    SerialNumber {
        uuid id PK
        string serial_no UK
        string status
        uuid sold_to_customer FK
    }
    OutboundOrder {
        uuid id PK
        uuid warehouse FK
        uuid customer FK
        string status
        string sales_order_code "loose→SalesOrder"
    }
    StockMovement {
        uuid id PK
        string reason
        int qty_delta
    }
```

> `OutboundOrder.sales_order_code` là **loose key** sang Sales (xem EXTENDING §3) —
> sẽ nâng thành FK khi sales↔wms gắn chặt.

---

## 5. Cross-cutting: Identity · Learning · Storage · Audit

```mermaid
erDiagram
    User }o--o| Customer : "customer (nếu là KH)"
    User ||--o{ AuditLog : actor
    QueryLog ||--o| GoldenExample : "source_log"

    User {
        uuid id PK
        string username UK
        string role
        uuid customer FK "null nếu nội bộ"
    }
    AuditLog {
        bigint id PK
        uuid user FK
        string action
        string entity
        string entity_id
        json diff
        string via "ui | bot"
    }
    QueryLog {
        uuid id PK
        text query
        json tools_used
        json confidence
    }
    GoldenExample {
        uuid id PK
        uuid source_log FK
        bool promoted
    }
    FileObject {
        uuid id PK
        string bucket
        string key
    }
    EventDeadLetter {
        uuid id PK
        string channel
        json payload
    }
```

- `User.role` ∈ {customer, sales, warehouse, service, manager, admin} — xem `roles.py`.
- `User.customer` chỉ set khi user là **khách** (đăng nhập tra cứu); nội bộ = null.
- `EventDeadLetter`: event xử lý thất bại → lưu để retry (hỗ trợ event bus).

---

## 6. Audit FK dùng chung (không vẽ trong ERD trên)

Mọi model kế thừa `BaseModel` (apps/common) có sẵn 3 FK tới `User`, **bỏ khỏi sơ đồ**
để gọn. Các model có audit FK: Customer, Contact, Lead, Opportunity, Quote, Visit,
Ticket, SalesOrder, Payment, Warehouse, Zone (qua warehouse), SerialNumber,
ASN, InboundOrder, OutboundOrder, FileObject.

```
BaseModel (abstract):
    id          UUID7 PK
    created_at  / created_by → User
    updated_at  / updated_by → User
SoftDeleteMixin (abstract):
    is_deleted  / deleted_at / deleted_by → User
```

---

## 7. Bảng tổng hợp 56 model theo app

| App | Số model | Model |
|---|---|---|
| accounts | 1 | User |
| common | 1 | AuditLog |
| catalog | 13 | Torch, Part, CompatibilityEdge, TorchPartMapping, ProcessEdge, GasFlowEdge, ConsumableSet, ConsumableSetItem, NegativeRule, CategoryVocabulary, PartNoAlias, PartEmbedding, SeedMeta |
| crm | 8 | Customer, Contact, Lead, Opportunity, Quote, QuoteLine, Visit, Ticket |
| sales | 3 | SalesOrder, SalesOrderLine, Payment |
| wms | 13 | Warehouse, Zone, Bin, InventoryItem, SerialNumber, Lot, ASN, InboundOrder, InboundLine, OutboundOrder, OutboundLine, PickListItem, StockMovement |
| analytics | 0 | (đọc qua aggregate/MV, không có bảng riêng) |
| storage | 1 | FileObject |
| learning | 3 | QueryLog, GoldenExample, EventDeadLetter |

**Tổng: 43 model nghiệp vụ** (chưa tính bảng phụ Django như token blacklist).

---

## 8. Ba điểm thiết kế cần nhớ khi đụng schema

1. **Catalog PK là chuỗi** (`tokin_part_no`, `model_code`), không UUID. FK trỏ tới
   catalog phải dùng đúng kiểu chuỗi.
2. **Hard FK vs loose key**: Sales dùng hard FK tới Part/Torch (toàn vẹn);
   CRM/WMS dùng loose key ở ranh giới giữa app (linh hoạt, tránh circular). Xem nét
   `..` ở §1 và ghi chú từng bảng.
3. **PartEmbedding** có `VectorField(1024)` + HNSW — migration portable Postgres/SQLite
   (xem EXTENDING §9.1). Đừng auto-generate migration cho bảng này.
