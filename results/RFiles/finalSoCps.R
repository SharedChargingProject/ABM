# clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory (RStudio)
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)
setwd('..')
library(readr)
library(dplyr)
library(ggplot2)

# load csv
csv_file <- "test_run_seed_05520_days_001_strategy_FCFS_EVsMAX_002_CHGF_01_CHGS_00_maxGrid_2000.csv"
df <- read_csv(csv_file, show_col_types = FALSE)

# extract final SoCp values for EVs
df_final <- df %>%
  filter(grepl("^ev_", agent),
         field == "final_SoCp") %>%
  mutate(value = as.numeric(value))

# plot distribution
ggplot(df_final, aes(x = value)) +
  geom_histogram(bins = 20) +
  labs(x = "Final SoC (%)",
       y = "Count",
       title = "Distribution of Final SoCp") +
  theme_minimal()

# extract energy_sandbox power output
df_power <- df %>%
  filter(agent == "energy_sandbox",
         field == "power_output_kWh") %>%
  mutate(time = as.POSIXct(time, origin = "1970-01-01", tz = "UTC"),
         value = as.numeric(value)) %>%
  arrange(time)

# plot time series
ggplot(df_power, aes(x = time, y = value)) +
  geom_line() +
  labs(x = "Time",
       y = "Power Output (kW)",
       title = "Energy Sandbox Power Output Over Time") +
  theme_minimal()

library(dplyr)
library(ggplot2)
library(scales)
library(RColorBrewer)

# --- SoCp data ---
df_socp <- df %>%
  filter(grepl("^ev_", agent), field == "SoCp") %>%
  mutate(time = as.POSIXct(time, origin = "1970-01-01", tz = "UTC"),
         value = as.numeric(value),
         ev_label = paste0("EV ", sub("ev_", "", agent)))

# --- charger_id data (exclude -1) ---
df_charger <- df %>%
  filter(grepl("^ev_", agent), field2 == "charger_id", value2 != -1) %>%
  transmute(time = as.POSIXct(time, origin = "1970-01-01", tz = "UTC"),
            agent,
            charger_label = paste0("CHG ", value2)) %>%
  distinct(time, agent, .keep_all = TRUE)

# --- join ---
df_plot <- df_socp %>%
  left_join(df_charger, by = c("time", "agent"))

# --- color palettes: EVs vs Chargers (chargers high-contrast) ---
ev_ids  <- sort(unique(df_plot$ev_label))
chg_ids <- sort(unique(na.omit(df_plot$charger_label)))

ev_colors <- setNames(hue_pal()(length(ev_ids)), ev_ids)

# Dark2 up to 8; if more, fall back to hue but keep separation via different palette
if (length(chg_ids) <= 8) {
  chg_colors <- setNames(brewer.pal(max(3, length(chg_ids)), "Dark2")[seq_along(chg_ids)], chg_ids)
} else {
  chg_colors <- setNames(hue_pal(l = 40, c = 120)(length(chg_ids)), chg_ids)
}

all_colors <- c(ev_colors, chg_colors)

# --- plot ---
ggplot(df_plot, aes(x = time, y = value)) +
  geom_line(aes(color = ev_label), linewidth = 1) +
  geom_point(
    data = df_plot %>% filter(!is.na(charger_label)),
    aes(color = charger_label),
    size = 2
  ) +
  scale_color_manual(values = all_colors, breaks = c(ev_ids, chg_ids)) +
  labs(x = "Time",
       y = "SoC (%)",
       color = "Legend",
       title = "SoCp Progress Over Time") +
  theme_minimal()

  

