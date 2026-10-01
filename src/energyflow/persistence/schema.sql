CREATE TABLE IF NOT EXISTS energy_readings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sensor_id text NOT NULL,
    recorded_at timestamptz NOT NULL,
    power_watts double precision NOT NULL,
    CONSTRAINT energy_readings_sensor_id_format CHECK (
        char_length(sensor_id) BETWEEN 1 AND 64
        AND sensor_id ~ '^[A-Za-z0-9][A-Za-z0-9_-]*$'
    ),
    CONSTRAINT energy_readings_power_non_negative CHECK (power_watts >= 0),
    CONSTRAINT energy_readings_power_finite CHECK (
        power_watts = power_watts
        AND power_watts > '-Infinity'::float8
        AND power_watts < 'Infinity'::float8
        AND power_watts <> 'NaN'::float8
    )
);

CREATE INDEX IF NOT EXISTS energy_readings_sensor_recorded_at_idx
    ON energy_readings (sensor_id, recorded_at);
