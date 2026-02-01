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

-- Enable RLS on all tables
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
-- Enable RLS on all tables (Idempotent)
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_papers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_paper_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_paper_keywords ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.research_paper_comments ENABLE ROW LEVEL SECURITY;

-- 5.1 USERS POLICIES
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can view own profile' AND tablename = 'users') THEN
        CREATE POLICY "Users can view own profile" ON public.users FOR SELECT USING (auth.uid() = id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users can update own profile' AND tablename = 'users') THEN
        CREATE POLICY "Users can update own profile" ON public.users FOR UPDATE USING (auth.uid() = id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Doctors are public' AND tablename = 'users') THEN
        CREATE POLICY "Doctors are public" ON public.users FOR SELECT USING (role = 'doctor');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins can view all users' AND tablename = 'users') THEN
        CREATE POLICY "Admins can view all users" ON public.users FOR SELECT USING (auth.uid() IN (SELECT id FROM public.users WHERE role = 'admin'));
    END IF;
END $$;

-- 5.2 ARTICLES POLICIES
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Published articles are public' AND tablename = 'articles') THEN
        CREATE POLICY "Published articles are public" ON public.articles FOR SELECT USING (status = 'published');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Authors manage own articles' AND tablename = 'articles') THEN
        CREATE POLICY "Authors manage own articles" ON public.articles USING (auth.uid() = author_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins manage all articles' AND tablename = 'articles') THEN
        CREATE POLICY "Admins manage all articles" ON public.articles USING (auth.uid() IN (SELECT id FROM public.users WHERE role = 'admin'));
    END IF;
END $$;

-- 5.3 CHAT SESSIONS POLICIES
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users govern own sessions' AND tablename = 'chat_sessions') THEN
        CREATE POLICY "Users govern own sessions" ON public.chat_sessions USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins view all sessions' AND tablename = 'chat_sessions') THEN
        CREATE POLICY "Admins view all sessions" ON public.chat_sessions FOR SELECT USING (auth.uid() IN (SELECT id FROM public.users WHERE role = 'admin'));
    END IF;
END $$;

-- 5.4 CHAT MESSAGES POLICIES
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users view own messages' AND tablename = 'chat_messages') THEN
        CREATE POLICY "Users view own messages" ON public.chat_messages FOR SELECT 
        USING (EXISTS (SELECT 1 FROM public.chat_sessions WHERE id = chat_messages.session_id AND user_id = auth.uid()));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users insert own messages' AND tablename = 'chat_messages') THEN
        CREATE POLICY "Users insert own messages" ON public.chat_messages FOR INSERT 
        WITH CHECK (EXISTS (SELECT 1 FROM public.chat_sessions WHERE id = chat_messages.session_id AND user_id = auth.uid()));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins view all messages' AND tablename = 'chat_messages') THEN
        CREATE POLICY "Admins view all messages" ON public.chat_messages FOR SELECT 
        USING (auth.uid() IN (SELECT id FROM public.users WHERE role = 'admin'));
    END IF;
END $$;

-- 5.5 CONTEXT POLICIES
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Users view own contexts' AND tablename = 'conversation_contexts') THEN
        CREATE POLICY "Users view own contexts" ON public.conversation_contexts 
        USING (EXISTS (SELECT 1 FROM public.chat_sessions WHERE id = conversation_contexts.session_id AND user_id = auth.uid()));
    END IF;
END $$;

-- 5.6 RESEARCH DATA POLICIES
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Authenticated users view research papers' AND tablename = 'research_papers') THEN
        CREATE POLICY "Authenticated users view research papers" ON public.research_papers FOR SELECT USING (auth.role() = 'authenticated');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Authenticated users view paper scores' AND tablename = 'research_paper_scores') THEN
        CREATE POLICY "Authenticated users view paper scores" ON public.research_paper_scores FOR SELECT USING (auth.role() = 'authenticated');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Authenticated users view paper keywords' AND tablename = 'research_paper_keywords') THEN
        CREATE POLICY "Authenticated users view paper keywords" ON public.research_paper_keywords FOR SELECT USING (auth.role() = 'authenticated');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Authenticated users view paper comments' AND tablename = 'research_paper_comments') THEN
        CREATE POLICY "Authenticated users view paper comments" ON public.research_paper_comments FOR SELECT USING (auth.role() = 'authenticated');
    END IF;
END $$;

-- 5.7 ADMIN ONLY MANAGEMENT
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Admins manage research' AND tablename = 'research_papers') THEN
        CREATE POLICY "Admins manage research" ON public.research_papers USING (auth.uid() IN (SELECT id FROM public.users WHERE role = 'admin'));
    END IF;
END $$;
