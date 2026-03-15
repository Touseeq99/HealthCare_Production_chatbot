-- ==============================================================================
-- MIGRATION: Patient Clinical Notes Table
-- Run this in the Supabase SQL Editor (or via psql).
-- ==============================================================================

-- ── TABLE ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.patient_clinical_notes (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,

    -- Quick-access metadata (so LIST queries don't need to deserialise JSONB)
    file_path          TEXT NOT NULL,          -- e.g. dr.smith/2026-03-15_JD.json
    patient_initials   TEXT NOT NULL,
    patient_mrn        TEXT,
    date_of_admission  DATE,

    -- Full structured patient form stored as JSONB
    patient_data  JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── INDEXES ────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_pcn_user_id      ON public.patient_clinical_notes(user_id);
CREATE INDEX IF NOT EXISTS idx_pcn_updated_at   ON public.patient_clinical_notes(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pcn_initials     ON public.patient_clinical_notes(patient_initials);

-- ── AUTO-UPDATE updated_at ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_pcn_updated_at ON public.patient_clinical_notes;
CREATE TRIGGER trg_pcn_updated_at
    BEFORE UPDATE ON public.patient_clinical_notes
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ── ROW LEVEL SECURITY ────────────────────────────────────────────────────────
ALTER TABLE public.patient_clinical_notes ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    -- Doctors can only see their own patient records
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'Doctors manage own patient notes'
          AND tablename  = 'patient_clinical_notes'
    ) THEN
        CREATE POLICY "Doctors manage own patient notes"
            ON public.patient_clinical_notes
            USING (auth.uid() = user_id)
            WITH CHECK (auth.uid() = user_id);
    END IF;

    -- Admins can view all records (SELECT only)
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE policyname = 'Admins view all patient notes'
          AND tablename  = 'patient_clinical_notes'
    ) THEN
        CREATE POLICY "Admins view all patient notes"
            ON public.patient_clinical_notes
            FOR SELECT
            USING (
                auth.uid() IN (
                    SELECT id FROM public.users WHERE role = 'admin'
                )
            );
    END IF;
END $$;

-- ── GRANT (service role bypasses RLS anyway, but good practice) ───────────────
-- No extra grants needed — service role key used by backend bypasses RLS.
-- ==============================================================================
