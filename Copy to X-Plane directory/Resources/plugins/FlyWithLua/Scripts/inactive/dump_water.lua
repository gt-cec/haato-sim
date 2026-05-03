-- play_sounds.lua
-- Plays water sounds and decrements water resevoir when trigger is pulled


-- Load sound files using OpenAL
local water_sound = load_WAV_file(SCRIPT_DIRECTORY .. "../../../sounds/haato/water_sound_short.wav")


-- Create dataref to monitor
dataref("water_remaining", "custom/haato/water_remaining", "writable")

-- Track previous button state to detect changes (edge trigger)
local previous_button_state = 0.0

-- Track if a sound is currently playing to prevent overlap
local is_playing = false
local playing_start_time = 0
local sound_duration = 2.0  -- Default duration in seconds, adjust as needed

-- Function to check if sound has finished playing
local function update_playing_status()
    if is_playing then
        local elapsed = os.clock() - playing_start_time
        if elapsed >= sound_duration then
            is_playing = false
        end
    end
end

-- Function to play sound based on dataref value
function check_and_play_sound()
    update_playing_status()

    local current_button_state = button(0) and 1.0 or 0.0  -- Convert boolean to float (1.0 or 0.0)
    --print(current_button_state)
    set("custom/haato/trigger_pulled", current_button_state)

    -- Check if button state has changed from 0 to 1 (edge trigger - button press)

    if current_button_state == 1.0 and water_remaining > 0 then
        set("custom/haato/water_remaining", water_remaining - 1) -- Decrement water reservoir by 1

        -- Only play if not currently playing (prevent overlap)
        if not is_playing then
            print("play water")
            play_sound(water_sound)
            is_playing = true
            playing_start_time = os.clock()

        end
    end

    -- Update previous button state
    previous_button_state = current_button_state
end

-- Monitor dataref every frame
do_every_frame("check_and_play_sound()")
