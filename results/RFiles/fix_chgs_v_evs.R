# clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory (RStudio)
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)

library(readr)
library(dplyr)
library(ggplot2)

# load csv
csv_file <- "../simulation_results_chg_count_4_ev_count_varied.csv"
df <- read_csv(csv_file, show_col_types = FALSE)

# Charge duration is actually in SECONDS (despite the column name)
df <- df %>%
  mutate(
    chargeTime = as.numeric(Charge_duration) / 3600,  # seconds -> hours
    Num_vehicles = as.factor(Num_vehicles)
  ) %>%
  filter(is.finite(chargeTime), chargeTime >= 0)

# keep only Num_vehicles in 4, 8, 12, 16
df <- df %>% filter(Final_SoC_Percentage == 100)

df <- df %>%
  mutate(avg_charge_power = Energy_kWh / chargeTime)
# 1 hour bins
binw <- 0.5

df_binned <- df %>%
  mutate(avg_charge_power_bin = floor(avg_charge_power / binw) * binw) %>%
  count(Num_vehicles, avg_charge_power_bin, name = "freq") %>%
  group_by(Num_vehicles) %>%
  mutate(prob = freq / sum(freq)) %>%
  ungroup()

p <- ggplot(df_binned,
            aes(x = avg_charge_power_bin, y = prob, color = Num_vehicles, group = Num_vehicles)) +
  geom_line(linewidth = 1) +
  geom_point(size = 1.5) +
  labs(
    title = "Charge Duration Distribution by EV Count",
    x = "Charge Duration (hours)",
    y = "Probability",
    color = "EV count"
  ) +
  theme_minimal()

print(p)

exit()
# Waiting time is in SECONDS
df_wait <- read_csv(csv_file, show_col_types = FALSE) %>%
  mutate(
    waitTime = as.numeric(Waiting_time) / 3600,  # seconds -> hours
    Num_vehicles = as.factor(Num_vehicles)
  ) %>%
  filter(
    is.finite(waitTime),
    waitTime >= 0,
    waitTime < 2,
    # Num_vehicles %in% c(4, 5, 6, 8, 10)
  )

binw <- 0.25

df_wait_binned <- df_wait %>%
  mutate(wait_bin = floor(waitTime / binw) * binw) %>%
  count(Num_vehicles, wait_bin, name = "freq") %>%
  group_by(Num_vehicles) %>%
  mutate(prob = freq / sum(freq)) %>%
  ungroup()

p_wait <- ggplot(df_wait_binned,
                 aes(x = wait_bin, y = prob, color = Num_vehicles, group = Num_vehicles)) +
  geom_line(linewidth = 1) +
  geom_point(size = 1.5) +
  labs(
    title = "Waiting Time Distribution by EV Count",
    x = "Waiting Time (hours)",
    y = "Probability",
    color = "EV count"
  ) +
  theme_minimal()

print(p_wait)
