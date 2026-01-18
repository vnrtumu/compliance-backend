-- Add processing_start_time column to uploads table
ALTER TABLE uploads ADD COLUMN IF NOT EXISTS processing_start_time TIMESTAMP WITH TIME ZONE;
