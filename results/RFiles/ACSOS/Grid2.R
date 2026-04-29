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
library(lubridate)

strategies <- c("SWRM", "FCFS", "SHRD")

extract_power_metrics <- function(strategy) {
  file_name <- paste0(
    "avg_employee_seed_05520_days_003_strategy_", strategy,
    "_EVsMAX_100_CHGF_20_CHGS_00_maxGrid_1000.csv"
  )
  
  df <- read_csv(file_name, show_col_types = FALSE)
  
  ts_df <- df %>%
    filter(agent == "energy_sandbox") %>%
    filter(field %in% c(
      "power_output_grid_kW",
      "power_output_PV_kW",
      "current_pv_power_kW"
    )) %>%
    mutate(
      time = as.numeric(time),
      value = suppressWarnings(as.numeric(value)),
      signal = case_when(
        field == "power_output_grid_kW" ~ "grid_kw",
        field == "power_output_PV_kW" ~ "pv_kw",
        field == "current_pv_power_kW" ~ "pv_available_kw"
      )
    ) %>%
    filter(!is.na(time), !is.na(value), !is.na(signal)) %>%
    group_by(time, signal) %>%
    summarise(value = dplyr::last(value), .groups = "drop") %>%
    pivot_wider(names_from = signal, values_from = value) %>%
    arrange(time) %>%
    fill(grid_kw, pv_kw, pv_available_kw, .direction = "down") %>%
    filter(!is.na(grid_kw), !is.na(pv_kw), !is.na(pv_available_kw))
  
  interval_df <- ts_df %>%
    mutate(
      time_next = lead(time),
      dt_sec = time_next - time,
      dt_hr = dt_sec / 3600
    ) %>%
    filter(!is.na(dt_sec), dt_sec > 0)
  
  change_df <- ts_df %>%
    mutate(
      dt_sec_prev = time - lag(time),
      grid_delta_kw = abs(grid_kw - lag(grid_kw)),
      grid_ramp_kw_per_min = if_else(
        !is.na(dt_sec_prev) & dt_sec_prev > 0,
        grid_delta_kw / (dt_sec_prev / 60),
        NA_real_
      )
    )
  
  grid_energy_kWh <- sum(interval_df$grid_kw * interval_df$dt_hr, na.rm = TRUE)
  pv_energy_kWh <- sum(interval_df$pv_kw * interval_df$dt_hr, na.rm = TRUE)
  pv_available_energy_kWh <- sum(interval_df$pv_available_kw * interval_df$dt_hr, na.rm = TRUE)
  total_energy_kWh <- grid_energy_kWh + pv_energy_kWh
  
  tibble(
    strategy = strategy,
    grid_peak_kW = max(ts_df$grid_kw, na.rm = TRUE),
    grid_fastest_change_kW_per_min = max(change_df$grid_ramp_kw_per_min, na.rm = TRUE),
    grid_energy_kWh = grid_energy_kWh,
    pv_energy_kWh = pv_energy_kWh,
    pv_available_energy_kWh = pv_available_energy_kWh,
    pv_share_of_supply_pct = ifelse(total_energy_kWh > 0, 100 * pv_energy_kWh / total_energy_kWh, NA_real_),
    pv_utilization_of_available_pct = ifelse(pv_available_energy_kWh > 0, 100 * pv_energy_kWh / pv_available_energy_kWh, NA_real_)
  )
}

comparison_tbl <- bind_rows(lapply(strategies, extract_power_metrics)) %>%
  mutate(across(where(is.numeric), ~ round(.x, 2)))

print(comparison_tbl)

write_csv(comparison_tbl, "strategy_power_comparison.csv")
