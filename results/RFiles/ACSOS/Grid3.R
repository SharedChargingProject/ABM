# clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory (RStudio)
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)
setwd("../..")

library(readr)
library(dplyr)
library(ggplot2)
library(lubridate)
library(svglite)

strategy <- "FCFS"
file_name <- paste0(
  "avg_employee_seed_05520_days_003_strategy_",
  strategy,
  "_EVsMAX_012_CHGF_01_CHGS_02_maxGrid_1000.csv"
)

df <- read_csv(
  file_name,
  col_types = cols(.default = col_character())
)

power_max <- df %>%
  filter(agent == "energy_sandbox", field == "power_output_kW") %>%
  mutate(value = suppressWarnings(as.numeric(value))) %>%
  summarise(mx = max(value, na.rm = TRUE)) %>%
  pull(mx)

pv_avail_max <- df %>%
  filter(agent == "energy_sandbox", field == "current_pv_power_kW") %>%
  mutate(value = suppressWarnings(as.numeric(value))) %>%
  summarise(mx = max(value, na.rm = TRUE)) %>%
  pull(mx)

price_max <- df %>%
  filter(agent == "env", field == "energy_price") %>%
  mutate(value = suppressWarnings(as.numeric(value))) %>%
  summarise(mx = max(value, na.rm = TRUE)) %>%
  pull(mx)

plot_df <- df %>%
  filter(
    (agent == "energy_sandbox" & field %in% c(
      "power_output_grid_kW",
      "power_output_PV_kW",
      "current_pv_power_kW"
    )) |
      (agent == "env" & field == "energy_price")
  ) %>%
  transmute(
    time = as_datetime(as.numeric(time), tz = "Europe/Vienna"),
    signal = case_when(
      field == "power_output_grid_kW" ~ "Grid usage",
      field == "power_output_PV_kW" ~ "PV usage",
      field == "current_pv_power_kW" ~ "Max PV available",
      field == "energy_price" ~ "Energy price"
    ),
    value = suppressWarnings(as.numeric(value))
  ) %>%
  filter(!is.na(time), !is.na(signal), !is.na(value)) %>%
  group_by(time, signal) %>%
  summarise(value = mean(value), .groups = "drop") %>%
  mutate(
    value_norm = case_when(
      signal == "Grid usage" ~ value / power_max,
      signal == "PV usage" ~ value / power_max,
      signal == "Max PV available" ~ value / pv_avail_max,
      signal == "Energy price" ~ value / price_max
    )
  ) %>%
  arrange(signal, time)

ggplot(plot_df, aes(x = time, y = value_norm, color = signal)) +
  geom_step(
    data = filter(plot_df, signal %in% c("Grid usage", "PV usage")),
    linewidth = 1,
    alpha = 0.8
  ) +
  geom_step(
    data = filter(plot_df, signal == "Max PV available"),
    linewidth = 1,
    linetype = "dotdash"
  ) +
  geom_step(
    data = filter(plot_df, signal == "Energy price"),
    linewidth = 1,
    linetype = "dashed"
  ) +
  labs(
    x = "Time",
    y = "Value relative to maximum",
    color = "Signal"
  ) +
  theme_minimal() +
  theme(
    legend.position = "bottom",
    legend.title = element_blank(),
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 14),
    legend.text = element_text(size = 12)
  )

ggsave(
  paste0(strategy, "_grid_usage_plot_normalized.PNG"),
  width = 10,
  height = 6
)