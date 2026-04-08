-- Local pgvector schema for Circuitron
-- Equivalent to setup_supabase.sql but without RLS (not needed for direct psycopg2 connections)
--
-- Run once against your local Postgres instance:
--   psql -h <host> -U <user> -d <dbname> -f setup_pgvector_local.sql
--
-- Prerequisites:
--   1. pgvector extension available (apt: postgresql-<ver>-pgvector)
--   2. Database already created: CREATE DATABASE circuitron;
--
-- Embedding dimensions by provider:
--   OpenAI text-embedding-3-small : 1536
--   Ollama nomic-embed-text        : 768   <-- default for local/offline use
--   Ollama mxbai-embed-large       : 1024
--
-- MIGRATION WARNING: changing EMBEDDING_DIMENSIONS after data is loaded requires
-- dropping and recreating the tables (ALTER COLUMN is not supported for vector type).
-- Set EMBEDDING_PROVIDER and EMBEDDING_MODEL in mcp.env before first run.

CREATE EXTENSION IF NOT EXISTS vector;

-- Drop tables if they exist (safe to re-run)
DROP TABLE IF EXISTS crawled_pages;
DROP TABLE IF EXISTS code_examples;
DROP TABLE IF EXISTS sources;

CREATE TABLE sources (
    source_id text PRIMARY KEY,
    summary text,
    total_word_count integer DEFAULT 0,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL
);

CREATE TABLE crawled_pages (
    id bigserial PRIMARY KEY,
    url varchar NOT NULL,
    chunk_number integer NOT NULL,
    content text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_id text NOT NULL,
    embedding vector(768),
    created_at timestamptz DEFAULT now() NOT NULL,
    UNIQUE (url, chunk_number),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE INDEX ON crawled_pages USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_crawled_pages_metadata ON crawled_pages USING gin (metadata);
CREATE INDEX idx_crawled_pages_source_id ON crawled_pages (source_id);

CREATE OR REPLACE FUNCTION match_crawled_pages (
    query_embedding vector(768),
    match_count int DEFAULT 10,
    filter jsonb DEFAULT '{}'::jsonb,
    source_filter text DEFAULT NULL
) RETURNS TABLE (
    id bigint,
    url varchar,
    chunk_number integer,
    content text,
    metadata jsonb,
    source_id text,
    similarity float
)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT
        id, url, chunk_number, content, metadata, source_id,
        1 - (crawled_pages.embedding <=> query_embedding) AS similarity
    FROM crawled_pages
    WHERE metadata @> filter
      AND (source_filter IS NULL OR source_id = source_filter)
    ORDER BY crawled_pages.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

CREATE TABLE code_examples (
    id bigserial PRIMARY KEY,
    url varchar NOT NULL,
    chunk_number integer NOT NULL,
    content text NOT NULL,
    summary text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_id text NOT NULL,
    embedding vector(768),
    created_at timestamptz DEFAULT now() NOT NULL,
    UNIQUE (url, chunk_number),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE INDEX ON code_examples USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_code_examples_metadata ON code_examples USING gin (metadata);
CREATE INDEX idx_code_examples_source_id ON code_examples (source_id);

CREATE OR REPLACE FUNCTION match_code_examples (
    query_embedding vector(768),
    match_count int DEFAULT 10,
    filter jsonb DEFAULT '{}'::jsonb,
    source_filter text DEFAULT NULL
) RETURNS TABLE (
    id bigint,
    url varchar,
    chunk_number integer,
    content text,
    summary text,
    metadata jsonb,
    source_id text,
    similarity float
)
LANGUAGE plpgsql AS $$
#variable_conflict use_column
BEGIN
    RETURN QUERY
    SELECT
        id, url, chunk_number, content, summary, metadata, source_id,
        1 - (code_examples.embedding <=> query_embedding) AS similarity
    FROM code_examples
    WHERE metadata @> filter
      AND (source_filter IS NULL OR source_id = source_filter)
    ORDER BY code_examples.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
