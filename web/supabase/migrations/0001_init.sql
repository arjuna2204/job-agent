-- Job Agent website: core schema
-- Users sign in with Supabase Auth (magic link). Everything a user owns is keyed by auth.users.id.

-- Beta allowlist: only these emails may sign in (checked by the app before sending a magic link
-- and enforced again by the trigger below).
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.beta_allowlist (
  email text primary key,
  added_at timestamptz not null default now()
);
alter table public.beta_allowlist enable row level security;
-- no policies: only the service role can read/write it

-- Profile = everything the extension needs to fill a form.
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  first_name text,
  last_name text,
  phone text,
  linkedin_url text,
  website_url text,
  current_location text,
  school text,
  degree text,
  graduation text,
  current_title text,
  current_company text,
  work_authorized_us boolean,
  needs_sponsorship boolean,
  notice_period text default '2 weeks',
  how_heard text default 'Company careers page',
  why_company_template text,         -- uses [Company] and [Product] placeholders
  exceptional_text text,
  extra_answers jsonb not null default '{}'::jsonb,  -- {"question keyword": "answer"}
  eeo jsonb not null default '{}'::jsonb,            -- optional voluntary answers
  resume_path text,                  -- storage path in the "resumes" bucket
  resume_alt_path text,              -- optional second (e.g. sales/GTM) resume
  extension_token text unique default encode(extensions.gen_random_bytes(24), 'hex'),
  daily_limit int not null default 20,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
create policy "own profile read"   on public.profiles for select using (auth.uid() = id);
create policy "own profile update" on public.profiles for update using (auth.uid() = id);
create policy "own profile insert" on public.profiles for insert with check (auth.uid() = id);

-- What kind of jobs the user wants.
create table if not exists public.preferences (
  user_id uuid primary key references auth.users(id) on delete cascade,
  title_keywords text[] not null default '{}',     -- e.g. {analyst, "business development", credit}
  exclude_keywords text[] not null default '{senior, director, manager, "vice president", principal, staff, lead, intern}',
  locations text[] not null default '{}',          -- e.g. {"new york", brooklyn, "jersey city"}
  remote_ok boolean not null default true,
  max_years int not null default 2,                -- skip postings that ask for more than this
  max_age_days int not null default 7,
  resume_alt_keywords text[] not null default '{sales, sdr, bdr, "business development", gtm, "go-to-market", partnerships, growth}',
  paused boolean not null default false,
  updated_at timestamptz not null default now()
);
alter table public.preferences enable row level security;
create policy "own prefs read"   on public.preferences for select using (auth.uid() = user_id);
create policy "own prefs write"  on public.preferences for insert with check (auth.uid() = user_id);
create policy "own prefs update" on public.preferences for update using (auth.uid() = user_id);

-- Shared job pool, written by the finder (service role).
create table if not exists public.jobs (
  id text primary key,                 -- "ats:slug:postingId"
  company text not null,
  title text not null,
  location text,
  remote boolean default false,
  department text,
  compensation text,
  posted timestamptz,
  first_seen timestamptz default now(),
  url text,
  apply_url text,
  ats text,                            -- greenhouse | lever | ashby | workday | other
  min_years int,
  description text,
  open boolean not null default true
);
create index if not exists jobs_open_posted on public.jobs(open, posted desc);
alter table public.jobs enable row level security;
create policy "jobs readable by signed-in users" on public.jobs for select to authenticated using (true);

-- One row per (user, job) the matcher picked for that user.
create type public.match_status as enum ('new', 'approved', 'skipped', 'applying', 'applied', 'needs_you', 'failed');
create table if not exists public.matches (
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id text not null references public.jobs(id) on delete cascade,
  status public.match_status not null default 'new',
  score int not null default 0,
  reason text,
  resume_choice text not null default 'main',   -- main | alt
  note text,                                    -- why it needs you / failed
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  applied_at timestamptz,
  primary key (user_id, job_id)
);
create index if not exists matches_user_status on public.matches(user_id, status, score desc);
alter table public.matches enable row level security;
create policy "own matches read"   on public.matches for select using (auth.uid() = user_id);
create policy "own matches update" on public.matches for update using (auth.uid() = user_id);

-- Jobs a user applied to elsewhere (so the matcher never suggests them again).
create table if not exists public.applied_elsewhere (
  user_id uuid not null references auth.users(id) on delete cascade,
  company text not null,
  title text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, company, title)
);
alter table public.applied_elsewhere enable row level security;
create policy "own applied read"  on public.applied_elsewhere for select using (auth.uid() = user_id);
create policy "own applied write" on public.applied_elsewhere for insert with check (auth.uid() = user_id);
create policy "own applied del"   on public.applied_elsewhere for delete using (auth.uid() = user_id);

-- New auth user -> must be on the allowlist; create empty profile + preferences.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.beta_allowlist where lower(email) = lower(new.email)) then
    raise exception 'This beta is invite-only';
  end if;
  insert into public.profiles (id, email) values (new.id, new.email) on conflict do nothing;
  insert into public.preferences (user_id) values (new.id) on conflict do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Private resume storage: each user can only touch files under "<their uid>/".
insert into storage.buckets (id, name, public) values ('resumes', 'resumes', false)
  on conflict (id) do nothing;
create policy "own resumes read" on storage.objects for select
  using (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "own resumes write" on storage.objects for insert
  with check (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "own resumes update" on storage.objects for update
  using (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "own resumes delete" on storage.objects for delete
  using (bucket_id = 'resumes' and (storage.foldername(name))[1] = auth.uid()::text);
