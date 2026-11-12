CREATE TABLE audit_events (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor_id     uuid NOT NULL,
  patient_id   uuid,
  action       text NOT NULL,
  resource     text NOT NULL,
  resource_id  uuid,
  at           timestamptz NOT NULL DEFAULT now(),
  request_id   text,
  details      jsonb NOT NULL DEFAULT '{}'::jsonb
)
--@@
CREATE INDEX audit_patient_at ON audit_events (patient_id, at DESC)
--@@
CREATE INDEX audit_actor_at ON audit_events (actor_id, at DESC)
--@@
CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'P0001', HINT = 'AUDIT_APPEND_ONLY';
END $$
--@@
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION audit_append_only()
