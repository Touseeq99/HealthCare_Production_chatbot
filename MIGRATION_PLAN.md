# Supabase Migration Plan

## Phase 1: Setup & Configuration
- [x] **Dependencies**: Add `supabase` to `requirements.txt`.
- [x] **Environment**: Update `config.py` to include `SUPABASE_URL` and `SUPABASE_KEY`.
- [x] **Database Connection**: Updated models to support Supabase architecture.

## Phase 2: Database Schema Refactor
**Goal**: Align local models with Supabase's architecture (Postgres + GoTrue Auth).
- [x] **User Model**: 
    - Change `id` from `Integer` to `UUID` to match Supabase's `auth.users` ID.
    - Remove password fields (`hashed_password`, `salt`) - Supabase handles this.
    - Remove custom token fields (`email_verification_token`, `password_reset_token`) - Supabase handles this.
    - Added 'unassigned' role for onboarding.
- [x] **Foreign Keys**: Update all related tables (`Article`, `ChatSession`, etc.) to use `UUID` for `user_id`.

## Phase 3: Authentication Layer Replacement
**Goal**: Replace custom `api/auth.py` with Supabase Auth.
- [x] **Auth Utilities**: Created `utils/supabase_client.py`.
- [x] **Auth Endpoints**: Rewrote `api/auth.py` for `signUp`, `signIn`, and added `/complete-profile`.
- [x] **Middleware**: Updated `utils/auth_dependencies.py` to verify Supabase JWTs via `get_user()`.

## Phase 4: Security (RLS)
- [x] **SQL Scripts**: Generated `supabase_setup.sql` with:
    - `users` (Profile Sync Trigger)
    - `chat_sessions` (RLS)
    - `articles` (RLS)

## Phase 5: Cleanup
- [x] Removed unused files:
    - `api/email_auth.py`
    - `utils/hash_password.py`
    - `utils/auth_service.py`
    - `utils/token_validator.py`
    - `utils/email_service.py`
    - `utils/token_blacklist_db.py`
    - `utils/refresh_token_service.py`
    - `utils/auth_security.py`
    - `utils/query_optimizer.py`
    - `api/doctor_chat.py` (v1)
- [x] Updated `config.py` to remove legacy auth settings.
- [x] Updated `clear_database.py` for new schema.

## Final Handover
- [x] Created `FRONTEND_AUTH_GUIDE.md` for the frontend team.
