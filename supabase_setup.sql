-- ==============================================================================
-- 1. ENUMS
-- ==============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_roles') THEN
        CREATE TYPE user_roles AS ENUM ('patient', 'doctor', 'admin', 'unassigned');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'session_types') THEN
        CREATE TYPE session_types AS ENUM ('patient', 'doctor');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'session_status') THEN
        CREATE TYPE session_status AS ENUM ('active', 'archived', 'deleted');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'message_types') THEN
        CREATE TYPE message_types AS ENUM ('user', 'assistant', 'system');
    END IF;
END$$;

-- ==============================================================================
-- 2. TABLES
-- ==============================================================================

-- USERS TABLE (Linked to Supabase Auth)
CREATE TABLE IF NOT EXISTS public.users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    role user_roles NOT NULL DEFAULT 'unassigned',
    name TEXT NOT NULL DEFAULT '',
    surname TEXT NOT NULL DEFAULT '',
    phone TEXT,
    specialization TEXT,
    doctor_register_number TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ARTICLES TABLE
CREATE TABLE IF NOT EXISTS public.articles (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author_id UUID REFERENCES public.users(id),
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- CHAT SESSIONS TABLE
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES public.users(id) NOT NULL,
    session_name TEXT,
    session_type session_types NOT NULL DEFAULT 'patient',
    status session_status DEFAULT 'active',
    session_data JSONB DEFAULT '{}'::jsonb,
    message_count INTEGER DEFAULT 0,
    last_message_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- CHAT MESSAGES TABLE
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES public.chat_sessions(id) ON DELETE CASCADE NOT NULL,
    content TEXT NOT NULL,
    message_type message_types NOT NULL DEFAULT 'user',
    token_count INTEGER,
    model_used TEXT,
    message_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- CONVERSATION CONTEXTS TABLE
CREATE TABLE IF NOT EXISTS public.conversation_contexts (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES public.chat_sessions(id) ON DELETE CASCADE UNIQUE NOT NULL,
    context_summary TEXT,
    key_topics JSONB DEFAULT '[]'::jsonb,
    user_preferences JSONB DEFAULT '{}'::jsonb,
    medical_context JSONB DEFAULT '{}'::jsonb,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- RESEARCH PAPERS
CREATE TABLE IF NOT EXISTS public.research_papers (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    total_score INTEGER NOT NULL,
    confidence INTEGER NOT NULL,
    paper_type TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- RESEARCH PAPER SCORES
CREATE TABLE IF NOT EXISTS public.research_paper_scores (
    id SERIAL PRIMARY KEY,
    research_paper_id INTEGER REFERENCES public.research_papers(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    score INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    max_score INTEGER DEFAULT 10
);

-- RESEARCH PAPER KEYWORDS
CREATE TABLE IF NOT EXISTS public.research_paper_keywords (
    id SERIAL PRIMARY KEY,
    research_paper_id INTEGER REFERENCES public.research_papers(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL
);

-- RESEARCH PAPER COMMENTS
CREATE TABLE IF NOT EXISTS public.research_paper_comments (
    id SERIAL PRIMARY KEY,
    research_paper_id INTEGER REFERENCES public.research_papers(id) ON DELETE CASCADE,
    comment TEXT NOT NULL,
    is_penalty BOOLEAN DEFAULT FALSE
);

-- ==============================================================================
-- 3. INDEXES
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON public.chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON public.chat_messages(session_id);

-- ==============================================================================
-- 4. AUTOMATIC PROFILE CREATION TRIGGER
-- ==============================================================================
CREATE OR REPLACE FUNCTION public.handle_new_user() 
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.users (
    id, 
    email, 
    name, 
    surname, 
    role, 
    specialization, 
    doctor_register_number, 
    created_at, 
    updated_at
  )
  VALUES (
    new.id, 
    new.email, 
    COALESCE(new.raw_user_meta_data->>'name', ''),
    COALESCE(new.raw_user_meta_data->>'surname', ''),
    COALESCE((new.raw_user_meta_data->>'role')::user_roles, 'unassigned'),
    new.raw_user_meta_data->>'specialization',
    new.raw_user_meta_data->>'doctor_register_number',
    new.created_at,
    new.created_at
  );
  RETURN new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- ==============================================================================
-- 5. ROW LEVEL SECURITY (RLS)
-- ==============================================================================
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.articles ENABLE ROW LEVEL SECURITY;

-- Users can view their own profile
CREATE POLICY "Users can view own profile" ON public.users FOR SELECT USING (auth.uid() = id);
-- Users can update their own profile
CREATE POLICY "Users can update own profile" ON public.users FOR UPDATE USING (auth.uid() = id);
-- Doctors are viewable by everyone
CREATE POLICY "Doctors are public" ON public.users FOR SELECT USING (role = 'doctor');
-- Chat sessions ownership
CREATE POLICY "Users govern own sessions" ON public.chat_sessions USING (auth.uid() = user_id);
-- Articles visibility
CREATE POLICY "Published articles are public" ON public.articles FOR SELECT USING (status = 'published');
CREATE POLICY "Authors manage own articles" ON public.articles USING (auth.uid() = author_id);













