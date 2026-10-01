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

CREATE TABLE IF NOT EXISTS disaggregation_results (
    reading_id uuid PRIMARY KEY REFERENCES energy_readings (id) ON DELETE CASCADE,
    total_power_watts double precision NOT NULL,
    refrigerator_watts double precision NOT NULL,
    air_conditioner_watts double precision NOT NULL,
    water_heater_watts double precision NOT NULL,
    other_watts double precision NOT NULL,
    CONSTRAINT disaggregation_results_power_non_negative CHECK (
        total_power_watts >= 0
        AND refrigerator_watts >= 0
        AND air_conditioner_watts >= 0
        AND water_heater_watts >= 0
        AND other_watts >= 0
    ),
    CONSTRAINT disaggregation_results_power_finite CHECK (
        total_power_watts = total_power_watts
        AND total_power_watts > '-Infinity'::float8
        AND total_power_watts < 'Infinity'::float8
        AND total_power_watts <> 'NaN'::float8
        AND refrigerator_watts = refrigerator_watts
        AND refrigerator_watts > '-Infinity'::float8
        AND refrigerator_watts < 'Infinity'::float8
        AND refrigerator_watts <> 'NaN'::float8
        AND air_conditioner_watts = air_conditioner_watts
        AND air_conditioner_watts > '-Infinity'::float8
        AND air_conditioner_watts < 'Infinity'::float8
        AND air_conditioner_watts <> 'NaN'::float8
        AND water_heater_watts = water_heater_watts
        AND water_heater_watts > '-Infinity'::float8
        AND water_heater_watts < 'Infinity'::float8
        AND water_heater_watts <> 'NaN'::float8
        AND other_watts = other_watts
        AND other_watts > '-Infinity'::float8
        AND other_watts < 'Infinity'::float8
        AND other_watts <> 'NaN'::float8
    ),
    CONSTRAINT disaggregation_results_estimates_match_total CHECK (
        abs(
            (refrigerator_watts + air_conditioner_watts + water_heater_watts + other_watts)
            - total_power_watts
        ) <= 0.000001
    )
);
