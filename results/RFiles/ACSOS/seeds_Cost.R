# Clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory in RStudio
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)
setwd("../..")

library(readr)
library(dplyr)
library(tidyr)
library(lubridate)
library(writexl)

exp_base_name <- "ACSOS/ACSOS"
N <- 8

seed_col <- "seed"
strategy_col <- "charging_column__strategy"

jain_index <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  n <- length(x)
  
  if (n == 0) return(NA_real_)
  if (sum(x) == 0) return(NA_real_)
  
  (sum(x)^2) / (n * sum(x^2))
}

safe_mean <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  if (length(x) == 0) return(NA_real_)
  mean(x)
}

safe_sd <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  if (length(x) <= 1) return(0)
  sd(x)
}

safe_min <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  if (length(x) == 0) return(NA_real_)
  min(x)
}

safe_max <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  if (length(x) == 0) return(NA_real_)
  max(x)
}

add_missing_numeric_columns <- function(data, cols) {
  for (col in cols) {
    if (!col %in% names(data)) {
      data[[col]] <- NA_real_
    }
  }
  data
}

process_one_experiment <- function(exp_i, exp_base_name, seed_col, strategy_col) {
  experiment_name <- paste0(exp_base_name, exp_i)
  file_name <- paste0(experiment_name, ".csv")
  
  if (!file.exists(file_name)) {
    warning("File not found, skipping: ", file_name)
    return(NULL)
  }
  
  df <- read_csv(
    file_name,
    col_types = cols(.default = col_character()),
    show_col_types = FALSE
  )
  
  required_cols <- c("time", "agent", "field", "value", seed_col, strategy_col)
  missing_cols <- setdiff(required_cols, names(df))
  
  if (length(missing_cols) > 0) {
    warning(
      "Skipping ", file_name,
      " because of missing columns: ",
      paste(missing_cols, collapse = ", ")
    )
    return(NULL)
  }
  
  base_df <- df %>%
    transmute(
      time_num = suppressWarnings(as.numeric(time)),
      time = as_datetime(time_num, tz = "Europe/Vienna"),
      seed = as.character(.data[[seed_col]]),
      strategy = as.character(.data[[strategy_col]]),
      agent = agent,
      field = field,
      value_num = suppressWarnings(as.numeric(value))
    ) %>%
    filter(!is.na(time_num))
  
  if (nrow(base_df) == 0) {
    warning("Skipping empty or invalid file: ", file_name)
    return(NULL)
  }
  
  days_per_seed <- base_df %>%
    group_by(strategy, seed) %>%
    summarise(
      days = floor((max(time_num, na.rm = TRUE) - min(time_num, na.rm = TRUE)) / 86400),
      .groups = "drop"
    )
  
  ev_final <- base_df %>%
    filter(grepl("^ev_", agent)) %>%
    filter(field %in% c("total_cost", "total_energy_received")) %>%
    filter(!is.na(value_num)) %>%
    arrange(strategy, seed, agent, field, time_num) %>%
    group_by(strategy, seed, agent, field) %>%
    summarise(value = dplyr::last(value_num), .groups = "drop") %>%
    pivot_wider(
      names_from = field,
      values_from = value
    ) %>%
    add_missing_numeric_columns(c("total_cost", "total_energy_received")) %>%
    mutate(
      total_cost = coalesce(total_cost, 0),
      total_energy_received = coalesce(total_energy_received, 0)
    )
  
  user_metrics_per_seed <- ev_final %>%
    filter(total_energy_received > 0) %>%
    mutate(
      user_energy_price = total_cost / total_energy_received
    ) %>%
    group_by(strategy, seed) %>%
    summarise(
      active_users = n(),
      avg_user_energy_price = safe_mean(user_energy_price),
      avg_user_totalcost = safe_mean(total_cost),
      Jain = jain_index(user_energy_price),
      .groups = "drop"
    )
  
  ev_soc_capacity_long <- base_df %>%
    filter(grepl("^ev_", agent)) %>%
    filter(field %in% c(
      "final_SoCp",
      "battery_capacity_kwh",
      "battery_capacity_kWh",
      "battery_capacity",
      "capacity_kwh",
      "capacity_kWh"
    )) %>%
    filter(!is.na(value_num)) %>%
    arrange(strategy, seed, agent, field, time_num) %>%
    group_by(strategy, seed, agent, field) %>%
    summarise(value = dplyr::last(value_num), .groups = "drop") %>%
    pivot_wider(
      names_from = field,
      values_from = value
    ) %>%
    add_missing_numeric_columns(c(
      "final_SoCp",
      "battery_capacity_kwh",
      "battery_capacity_kWh",
      "battery_capacity",
      "capacity_kwh",
      "capacity_kWh"
    )) %>%
    mutate(
      battery_capacity_kwh_final = coalesce(
        battery_capacity_kwh,
        battery_capacity_kWh,
        battery_capacity,
        capacity_kwh,
        capacity_kWh
      )
    )
  
  ev_soc_capacity_metrics_per_seed <- ev_soc_capacity_long %>%
    group_by(strategy, seed) %>%
    summarise(
      evs_with_final_SoCp = sum(!is.na(final_SoCp)),
      avg_final_SoCp = safe_mean(final_SoCp),
      sd_final_SoCp = safe_sd(final_SoCp),
      min_final_SoCp = safe_min(final_SoCp),
      max_final_SoCp = safe_max(final_SoCp),
      avg_battery_capacity_kwh = safe_mean(battery_capacity_kwh_final),
      sd_battery_capacity_kwh = safe_sd(battery_capacity_kwh_final),
      .groups = "drop"
    )
  
  power_long <- base_df %>%
    filter(agent == "energy_sandbox") %>%
    filter(field %in% c("power_output_grid_kW", "power_output_PV_kW")) %>%
    filter(!is.na(value_num)) %>%
    group_by(strategy, seed, time, field) %>%
    summarise(value = dplyr::last(value_num), .groups = "drop")
  
  power_wide <- power_long %>%
    pivot_wider(
      names_from = field,
      values_from = value
    ) %>%
    add_missing_numeric_columns(c("power_output_grid_kW", "power_output_PV_kW")) %>%
    arrange(strategy, seed, time) %>%
    group_by(strategy, seed) %>%
    fill(power_output_grid_kW, power_output_PV_kW, .direction = "down") %>%
    mutate(
      power_output_grid_kW = coalesce(power_output_grid_kW, 0),
      power_output_PV_kW = coalesce(power_output_PV_kW, 0),
      total_power_kW = power_output_grid_kW + power_output_PV_kW,
      
      next_time = lead(time),
      dt_h = as.numeric(difftime(next_time, time, units = "hours")),
      dt_h = if_else(is.na(dt_h) | dt_h < 0, 0, dt_h),
      
      PV_used_kWh = power_output_PV_kW * dt_h,
      Grid_used_kWh = power_output_grid_kW * dt_h,
      total_energy_used_kWh = total_power_kW * dt_h,
      
      grid_change_kW = abs(power_output_grid_kW - lag(power_output_grid_kW))
    ) %>%
    ungroup()
  
  energy_metrics_per_seed <- power_wide %>%
    group_by(strategy, seed) %>%
    summarise(
      PV_used = sum(PV_used_kWh, na.rm = TRUE),
      Grid_used = sum(Grid_used_kWh, na.rm = TRUE),
      total_energy_used = sum(total_energy_used_kWh, na.rm = TRUE),
      Grid_peak = safe_max(power_output_grid_kW),
      sharpest_Grid_change = safe_max(grid_change_kW),
      .groups = "drop"
    )
  
  per_seed_table <- days_per_seed %>%
    left_join(user_metrics_per_seed, by = c("strategy", "seed")) %>%
    left_join(ev_soc_capacity_metrics_per_seed, by = c("strategy", "seed")) %>%
    left_join(energy_metrics_per_seed, by = c("strategy", "seed"))
  
  final_table <- per_seed_table %>%
    group_by(strategy) %>%
    summarise(
      nseeds = n_distinct(seed),
      
      days_mean = safe_mean(days),
      days_sd = safe_sd(days),
      
      active_users_mean = safe_mean(active_users),
      active_users_sd = safe_sd(active_users),
      
      evs_with_final_SoCp_mean = safe_mean(evs_with_final_SoCp),
      evs_with_final_SoCp_sd = safe_sd(evs_with_final_SoCp),
      
      final_SoCp_mean = safe_mean(avg_final_SoCp),
      final_SoCp_sd = safe_sd(avg_final_SoCp),
      final_SoCp_min_mean = safe_mean(min_final_SoCp),
      final_SoCp_max_mean = safe_mean(max_final_SoCp),
      
      battery_capacity_kwh_mean = safe_mean(avg_battery_capacity_kwh),
      battery_capacity_kwh_sd = safe_sd(avg_battery_capacity_kwh),
      
      avg_user_energy_price_mean = safe_mean(avg_user_energy_price),
      avg_user_energy_price_sd = safe_sd(avg_user_energy_price),
      
      avg_user_totalcost_mean = safe_mean(avg_user_totalcost),
      avg_user_totalcost_sd = safe_sd(avg_user_totalcost),
      
      Jain_mean = safe_mean(Jain),
      Jain_sd = safe_sd(Jain),
      
      PV_used_mean = safe_mean(PV_used),
      PV_used_sd = safe_sd(PV_used),
      
      Grid_used_mean = safe_mean(Grid_used),
      Grid_used_sd = safe_sd(Grid_used),
      
      total_energy_used_mean = safe_mean(total_energy_used),
      total_energy_used_sd = safe_sd(total_energy_used),
      
      Grid_peak_mean = safe_mean(Grid_peak),
      Grid_peak_sd = safe_sd(Grid_peak),
      
      sharpest_Grid_change_mean = safe_mean(sharpest_Grid_change),
      sharpest_Grid_change_sd = safe_sd(sharpest_Grid_change),
      
      .groups = "drop"
    ) %>%
    mutate(
      `Exp.` = exp_i,
      .before = 1
    ) %>%
    select(
      `Exp.`, strategy, nseeds,
      days_mean, days_sd,
      active_users_mean, active_users_sd,
      evs_with_final_SoCp_mean, evs_with_final_SoCp_sd,
      final_SoCp_mean, final_SoCp_sd,
      final_SoCp_min_mean, final_SoCp_max_mean,
      battery_capacity_kwh_mean, battery_capacity_kwh_sd,
      avg_user_energy_price_mean, avg_user_energy_price_sd,
      avg_user_totalcost_mean, avg_user_totalcost_sd,
      Jain_mean, Jain_sd,
      PV_used_mean, PV_used_sd,
      Grid_used_mean, Grid_used_sd,
      total_energy_used_mean, total_energy_used_sd,
      Grid_peak_mean, Grid_peak_sd,
      sharpest_Grid_change_mean, sharpest_Grid_change_sd
    ) %>%
    mutate(
      days_mean = round(days_mean, 2),
      days_sd = round(days_sd, 2),
      
      active_users_mean = round(active_users_mean, 2),
      active_users_sd = round(active_users_sd, 2),
      
      evs_with_final_SoCp_mean = round(evs_with_final_SoCp_mean, 2),
      evs_with_final_SoCp_sd = round(evs_with_final_SoCp_sd, 2),
      
      final_SoCp_mean = round(final_SoCp_mean, 3),
      final_SoCp_sd = round(final_SoCp_sd, 3),
      final_SoCp_min_mean = round(final_SoCp_min_mean, 3),
      final_SoCp_max_mean = round(final_SoCp_max_mean, 3),
      
      battery_capacity_kwh_mean = round(battery_capacity_kwh_mean, 2),
      battery_capacity_kwh_sd = round(battery_capacity_kwh_sd, 2),
      
      avg_user_energy_price_mean = round(avg_user_energy_price_mean, 4),
      avg_user_energy_price_sd = round(avg_user_energy_price_sd, 4),
      
      avg_user_totalcost_mean = round(avg_user_totalcost_mean, 3),
      avg_user_totalcost_sd = round(avg_user_totalcost_sd, 3),
      
      Jain_mean = round(Jain_mean, 4),
      Jain_sd = round(Jain_sd, 4),
      
      PV_used_mean = round(PV_used_mean, 2),
      PV_used_sd = round(PV_used_sd, 2),
      
      Grid_used_mean = round(Grid_used_mean, 2),
      Grid_used_sd = round(Grid_used_sd, 2),
      
      total_energy_used_mean = round(total_energy_used_mean, 2),
      total_energy_used_sd = round(total_energy_used_sd, 2),
      
      Grid_peak_mean = round(Grid_peak_mean, 2),
      Grid_peak_sd = round(Grid_peak_sd, 2),
      
      sharpest_Grid_change_mean = round(sharpest_Grid_change_mean, 2),
      sharpest_Grid_change_sd = round(sharpest_Grid_change_sd, 2)
    )
  
  final_table
}

all_results <- lapply(
  seq_len(N),
  process_one_experiment,
  exp_base_name = exp_base_name,
  seed_col = seed_col,
  strategy_col = strategy_col
)

final_table <- bind_rows(all_results)

print(final_table)

output_file <- paste0(exp_base_name, "_1_to_", N, "_summary.xlsx")
write_xlsx(final_table, output_file)
