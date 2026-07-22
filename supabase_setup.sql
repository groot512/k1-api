-- K1 Recipe 테이블 생성 SQL
-- Supabase 대시보드 → SQL Editor → 이 내용 붙여넣기 → Run

-- 1. 레시피 테이블 생성
CREATE TABLE recipes (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  video_id TEXT NOT NULL UNIQUE,
  video_url TEXT DEFAULT '',
  video_title TEXT DEFAULT '',
  video_channel TEXT DEFAULT '',
  video_thumbnail TEXT DEFAULT '',
  recipe_title TEXT NOT NULL,
  recipe_description TEXT DEFAULT '',
  servings TEXT DEFAULT '',
  cook_time TEXT DEFAULT '',
  difficulty TEXT DEFAULT 'medium',
  ingredients JSONB DEFAULT '[]',
  steps JSONB DEFAULT '[]',
  tips JSONB DEFAULT '[]',
  transcript_length INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. RLS(Row Level Security) 활성화 + 공개 읽기/쓰기 허용
ALTER TABLE recipes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "누구나 레시피 읽기" ON recipes
  FOR SELECT USING (true);

CREATE POLICY "누구나 레시피 추가" ON recipes
  FOR INSERT WITH CHECK (true);

CREATE POLICY "누구나 레시피 수정" ON recipes
  FOR UPDATE USING (true);

-- 3. 인덱스 (검색 속도 향상)
CREATE INDEX idx_recipes_created_at ON recipes (created_at DESC);
CREATE INDEX idx_recipes_video_id ON recipes (video_id);
