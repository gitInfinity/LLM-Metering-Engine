### Error log

This is the persistent business logic error log that agents can read before working. Keep both open and resolved entries here. Add entries only for mistakes actually observed.

| ID | Trigger / mistake / cause | Correction | Prevention rule and repeatable check | Verification / status |
| --- | --- | --- | --- | --- |
| QUOTA-001 | Seeding raised a before-signup error: database-created signup time was compared with application time. Clock skew can reproduce this; the actual host clock difference was not measured. | Initialize the first period using signup time for both the anchor and lookup. | Run test_seed.py with the application clock five seconds behind signup; retain rejection of explicitly pre-signup lookups in quota_period. | Resolved: regression failed before the fix, all six tests passed after it, and live database initialization/seeding succeeded. |
| DOMAIN-001 | Tenant members were modeled as customers, confusing users with the organization paying for service. | Renamed Customer/customers to User/users; Stripe customer remains attached to Tenant. | Configure ORM mappers, create a User with a Tenant, verify membership in Tenant.users, and check that metadata contains users, not customers. | Resolved: relationship, foreign key, and PostgreSQL definition checks passed. |
