# i-Sumbong Entity Relationship Diagram

This ERD is based on the Django models in `base/models.py`.

```mermaid
erDiagram
    USER ||--o{ REPORT : submits
    USER ||--o{ REPORT : assigned_to
    USER ||--o{ NOTIFICATION : receives
    USER ||--o{ REPORT_ACTION : creates
    USER ||--o{ REPORT_COMMENT : writes
    USER ||--o| COMMUNITY_PROFILE : has
    USER ||--o| BARANGAY_ADMIN_PROFILE : has
    USER ||--o{ BULLETIN_POST : creates
    USER ||--o{ BULLETIN_POST_VIEW : views
    USER ||--o{ BULLETIN_POST_HISTORY : changes
    USER ||--o{ AUDIT_LOG : performs

    BARANGAY ||--o{ COMMUNITY_PROFILE : contains
    BARANGAY ||--o{ BARANGAY_ADMIN_PROFILE : manages
    BARANGAY ||--o{ BULLETIN_POST : publishes
    BARANGAY ||--o{ BULLETIN_POST_HISTORY : tracks
    BARANGAY ||--o{ AUDIT_LOG : scopes

    REPORT ||--o{ NOTIFICATION : triggers
    REPORT ||--o{ REPORT_ACTION : has
    REPORT ||--o{ REPORT_IMAGE : contains
    REPORT ||--o{ REPORT_COMMENT : has

    REPORT_COMMENT ||--o{ REPORT_COMMENT : replies

    BULLETIN_POST ||--o{ BULLETIN_IMAGE : contains
    BULLETIN_POST ||--o{ BULLETIN_POST_VIEW : records
    BULLETIN_POST ||--o{ BULLETIN_POST_HISTORY : logs

    USER {
        int id PK
        string username
        string email
        string password
        string first_name
        string last_name
        bool is_staff
        bool is_superuser
        bool is_active
        datetime date_joined
    }

    BARANGAY {
        int id PK
        string name UK
    }

    COMMUNITY_PROFILE {
        int id PK
        int user_id FK
        int barangay_id FK
        string address
        string phone_number
        string proof_of_residency
        string avatar
        string status
        int reviewed_by_id FK
        datetime reviewed_at
        text review_notes
        datetime created_at
    }

    BARANGAY_ADMIN_PROFILE {
        int id PK
        int user_id FK
        int barangay_id FK
    }

    REPORT {
        int id PK
        int user_id FK
        int assigned_to_id FK
        string title
        string location
        float latitude
        float longitude
        string priority
        text description
        string photo
        string status
        bool is_deleted
        datetime deleted_at
        datetime created_at
        datetime updated_at
        datetime resolved_at
    }

    REPORT_IMAGE {
        int id PK
        int report_id FK
        string image
        datetime created_at
    }

    REPORT_ACTION {
        int id PK
        int report_id FK
        int created_by_id FK
        string action
        text note
        datetime created_at
    }

    REPORT_COMMENT {
        int id PK
        int report_id FK
        int parent_id FK
        int user_id FK
        text message
        datetime created_at
        datetime updated_at
    }

    NOTIFICATION {
        int id PK
        int user_id FK
        int report_id FK
        string notif_type
        text message
        bool is_read
        string delivery_status
        int delivery_attempts
        datetime last_attempt_at
        text last_error
        datetime created_at
    }

    BULLETIN_POST {
        int id PK
        int barangay_id FK
        int created_by_id FK
        string title
        string category
        string post_type
        text content
        string priority
        string attachment
        bool is_pinned
        datetime expires_at
        datetime created_at
        datetime updated_at
    }

    BULLETIN_IMAGE {
        int id PK
        int post_id FK
        string image
        datetime created_at
    }

    BULLETIN_POST_VIEW {
        int id PK
        int post_id FK
        int user_id FK
        datetime seen_at
    }

    BULLETIN_POST_HISTORY {
        int id PK
        int bulletin_id FK
        int barangay_id FK
        int changed_by_id FK
        string action
        string title_snapshot
        string category_snapshot
        string priority_snapshot
        text content_snapshot
        bool is_pinned_snapshot
        datetime expires_at_snapshot
        string attachment_name
        datetime created_at
    }

    AUDIT_LOG {
        int id PK
        int actor_id FK
        int barangay_id FK
        string action
        string target_type
        int target_id
        string target_repr
        text reason
        json data
        datetime created_at
    }
```

## Relationship Notes

- `User` is Django's built-in auth user table.
- `CommunityProfile.user` and `BarangayAdminProfile.user` are unique one-to-one links to `User`.
- `Report.assigned_to` is optional and points to the admin user assigned to handle the report.
- `ReportComment.parent` is a self-reference for threaded replies.
- `BulletinPostView` has a unique pair of `post` and `user`, so each user can be counted once per bulletin.
- `AuditLog.target_type` and `target_id` behave like a lightweight polymorphic reference to different system records.
