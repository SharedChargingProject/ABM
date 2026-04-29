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
library(tidyr)
library(ggplot2)
library(lubridate)
library(svglite)
strategy <- "SWRM"
file_name <- paste0("avg_employee_seed_05520_days_003_strategy_",strategy,"_EVsMAX_012_CHGF_01_CHGS_02_maxGrid_1000.csv")

df <- read_csv(file_name, show_col_types = FALSE)

plot_df <- df %>%
  filter(agent == "energy_sandbox") %>%
  filter(field %in% c(
    "power_output_grid_kW",
    "power_output_PV_kW",
    "current_pv_power_kW"
  )) %>%
  mutate(
    time = as_datetime(as.numeric(time), tz = "Europe/Vienna"),
    value = suppressWarnings(as.numeric(value)),
    signal = case_when(
      field == "power_output_grid_kW" ~ "Grid usage",
      field == "power_output_PV_kW" ~ "PV usage",
      field == "current_pv_power_kW" ~ "Max PV available"
    )
  ) %>%
  filter(!is.na(time), !is.na(value), !is.na(signal)) %>%
  arrange(signal, time)


ggplot(
  plot_df,
  aes(x = time, y = value, color = signal, group = signal)
) +
  geom_line(
    aes(linetype = signal, alpha = signal),
    linewidth = 1.2
  ) +
  scale_linetype_manual(
    values = c(
      "Grid usage" = "solid",
      "PV usage" = "solid",
      "Max PV available" = "dashed"
    )
  ) +
  scale_alpha_manual(
    values = c(
      "Grid usage" = 0.5,
      "PV usage" = 0.5,
      "Max PV available" = 1
    )
  ) +
  guides(
    linetype = "none",
    alpha = "none"
  ) +
  labs(
    x = "Time",
    y = "Power (kW)",
    color = "Signal"
  ) +
  theme_minimal() +
  theme(
    legend.position = "bottom",
    legend.title = element_blank()
  )+ # set text size
  theme(
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 14),
    legend.text = element_text(size = 12)
  )

# save output as PNG
ggsave(paste0(strategy,"_grid_usage_plot.PNG"), width = 10, height = 6)
