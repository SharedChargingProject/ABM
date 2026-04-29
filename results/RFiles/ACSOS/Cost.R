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
library(purrr)

strategies <- c("SWRM", "FCFS", "SHRD")

jain_index <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  n <- length(x)
  
  if (n == 0) return(NA_real_)
  if (sum(x) == 0) return(NA_real_)
  
  (sum(x)^2) / (n * sum(x^2))
}

make_final_table <- function(strategy) {
  
  file_name <- paste0(
    "avg_employee_seed_05520_days_003_strategy_",
    strategy,
    "_EVsMAX_012_CHGF_01_CHGS_02_maxGrid_1000.csv"
  )
  
  df <- read_csv(
    file_name,
    col_types = cols(.default = col_character())
  )
  
  ev_cum <- df %>%
    filter(grepl("^ev_", agent)) %>%
    filter(field %in% c("total_cost", "total_energy_received")) %>%
    transmute(
      time  = as_datetime(as.numeric(time), tz = "Europe/Vienna"),
      day   = as_date(time, tz = "Europe/Vienna"),
      agent = agent,
      field = field,
      value = suppressWarnings(as.numeric(value))
    ) %>%
    filter(!is.na(value)) %>%
    arrange(agent, time)
  
  ev_day_end <- ev_cum %>%
    group_by(agent, day, field) %>%
    summarise(value = dplyr::last(value), .groups = "drop") %>%
    pivot_wider(
      names_from = field,
      values_from = value
    )
  
  all_days <- seq(min(ev_day_end$day), max(ev_day_end$day), by = "day")
  
  ev_daily <- ev_day_end %>%
    complete(agent, day = all_days) %>%
    arrange(agent, day) %>%
    group_by(agent) %>%
    fill(total_cost, total_energy_received, .direction = "down") %>%
    mutate(
      total_cost = coalesce(total_cost, 0),
      total_energy_received = coalesce(total_energy_received, 0),
      daily_cost = total_cost - lag(total_cost, default = 0),
      daily_energy_kWh = total_energy_received - lag(total_energy_received, default = 0)
    ) %>%
    ungroup() %>%
    mutate(
      daily_cost = pmax(daily_cost, 0),
      daily_energy_kWh = pmax(daily_energy_kWh, 0)
    )
  
  ev_daily_price <- ev_daily %>%
    filter(daily_energy_kWh > 0) %>%
    mutate(
      price_per_kWh = daily_cost / daily_energy_kWh,
      price_per_MWh = price_per_kWh * 1000
    )
  
  daily_table <- ev_daily_price %>%
    group_by(day) %>%
    summarise(
      active_users = n(),
      avg_energy_price_per_user_EUR_per_kWh = mean(price_per_kWh, na.rm = TRUE),
      avg_energy_price_per_user_EUR_per_MWh = mean(price_per_MWh, na.rm = TRUE),
      jains_index_energy_price = jain_index(price_per_kWh),
      total_daily_energy_kWh = sum(daily_energy_kWh, na.rm = TRUE),
      total_daily_cost_EUR = sum(daily_cost, na.rm = TRUE),
      .groups = "drop"
    )
  
  final_row <- daily_table %>%
    summarise(
      strategy = strategy,
      days = n(),
      avg_active_users = mean(active_users, na.rm = TRUE),
      avg_energy_price_per_user_EUR_per_kWh = mean(avg_energy_price_per_user_EUR_per_kWh, na.rm = TRUE),
      avg_energy_price_per_user_EUR_per_MWh = mean(avg_energy_price_per_user_EUR_per_MWh, na.rm = TRUE),
      avg_jains_index_energy_price = mean(jains_index_energy_price, na.rm = TRUE),
      avg_total_daily_energy_kWh = mean(total_daily_energy_kWh, na.rm = TRUE),
      avg_total_daily_cost_EUR = mean(total_daily_cost_EUR, na.rm = TRUE)
    )
  
  return(final_row)
}

final_table_all <- map_dfr(strategies, make_final_table)

print(final_table_all)