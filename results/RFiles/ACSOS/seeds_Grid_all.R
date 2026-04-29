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

strategies <- c("SWRM","FCFS","SHRD")
expriment_name_base <- "ACSOS/ACSOS"
ids <- 8
for (id in 1:ids) {
  expriment_name <- paste0(expriment_name_base, id)
  file_name <- paste0(expriment_name, ".csv")
  
  bin_minutes <- 15   # increase to 30 if the plot is too noisy
  
  df <- read_csv(
    file_name,
    col_types = cols(.default = col_character())
  )
  print(expriment_name)
  for (strategy in strategies) {
    print(strategy)
    # ------------------------------------------------------------
    # power signals
    # ------------------------------------------------------------
    power_df <- df %>%
      filter(
        charging_column__strategy == strategy,
        agent == "energy_sandbox",
        field %in% c(
          "power_output_grid_kW",
          "power_output_PV_kW",
          "current_pv_power_kW"
        )
      ) %>%
      transmute(
        time = as_datetime(suppressWarnings(as.numeric(time)), tz = "Europe/Vienna"),
        seed = seed,
        signal = case_when(
          field == "power_output_grid_kW" ~ "Grid usage",
          field == "power_output_PV_kW" ~ "PV usage",
          field == "current_pv_power_kW" ~ "Max PV available"
        ),
        value_kW = suppressWarnings(as.numeric(value))
      ) %>%
      filter(!is.na(time), !is.na(seed), !is.na(signal), !is.na(value_kW)) %>%
      mutate(
        time_bin = floor_date(time, unit = paste(bin_minutes, "minutes"))
      )
    
    # mean +- sd over seeds for Grid and PV usage
    seed_df <- power_df %>%
      filter(signal %in% c("Grid usage", "PV usage")) %>%
      group_by(time_bin, seed, signal) %>%
      summarise(
        value_kW = mean(value_kW, na.rm = TRUE),
        .groups = "drop"
      )
    
    band_df <- seed_df %>%
      group_by(time_bin, signal) %>%
      summarise(
        mean_value = mean(value_kW, na.rm = TRUE),
        sd_value = sd(value_kW, na.rm = TRUE),
        .groups = "drop"
      ) %>%
      mutate(
        sd_value = if_else(is.na(sd_value), 0, sd_value),
        ymin = pmax(mean_value - sd_value, 0),
        ymax = mean_value + sd_value
      )
    
    # single line for Max PV available
    pv_avail_df <- power_df %>%
      filter(signal == "Max PV available") %>%
      group_by(time_bin, signal) %>%
      summarise(
        value_kW = mean(value_kW, na.rm = TRUE),
        .groups = "drop"
      )
    
    # ------------------------------------------------------------
    # price signal
    # ------------------------------------------------------------
    price_df <- df %>%
      filter(
        charging_column__strategy == strategy,
        agent == "env",
        field == "energy_price"
      ) %>%
      transmute(
        time = as_datetime(suppressWarnings(as.numeric(time)), tz = "Europe/Vienna"),
        price_eur_kwh = suppressWarnings(as.numeric(value))
      ) %>%
      filter(!is.na(time), !is.na(price_eur_kwh)) %>%
      mutate(
        time_bin = floor_date(time, unit = paste(bin_minutes, "minutes"))
      ) %>%
      group_by(time_bin) %>%
      summarise(
        price_eur_kwh = mean(price_eur_kwh, na.rm = TRUE),
        .groups = "drop"
      )
    
    # ------------------------------------------------------------
    # secondary-axis scaling
    # map price to the left power axis, then invert on the right axis
    # ------------------------------------------------------------
    power_ymax <- max(
      c(band_df$ymax, pv_avail_df$value_kW),
      na.rm = TRUE
    )
    
    price_max <- max(price_df$price_eur_kwh, na.rm = TRUE)
    
    price_to_power <- power_ymax / price_max
    
    price_df <- price_df %>%
      mutate(
        price_scaled = price_eur_kwh * price_to_power
      )
    
    # ------------------------------------------------------------
    # plot
    # ------------------------------------------------------------
    p <- ggplot() +
      geom_ribbon(
        data = filter(band_df, signal == "Grid usage"),
        aes(x = time_bin, ymin = ymin, ymax = ymax, fill = signal),
        alpha = 0.18,
        show.legend = FALSE
      ) +
      geom_step(
        data = filter(band_df, signal == "Grid usage"),
        aes(x = time_bin, y = mean_value, color = signal),
        linewidth = 1
      ) +
      geom_ribbon(
        data = filter(band_df, signal == "PV usage"),
        aes(x = time_bin, ymin = ymin, ymax = ymax, fill = signal),
        alpha = 0.18,
        show.legend = FALSE
      ) +
      geom_step(
        data = filter(band_df, signal == "PV usage"),
        aes(x = time_bin, y = mean_value, color = signal),
        linewidth = 1
      ) +
      geom_step(
        data = pv_avail_df,
        aes(x = time_bin, y = value_kW, color = signal),
        linewidth = 1,
        linetype = "dotdash"
      ) +
      geom_step(
        data = price_df,
        aes(x = time_bin, y = price_scaled, color = "Energy price"),
        linewidth = 1,
        linetype = "dashed"
      ) +
      labs(
        x = "Time",
        y = "Power (kW)",
        color = "Signal"
      ) +
      scale_y_continuous(
        name = "Power (kW)",
        sec.axis = sec_axis(
          ~ . / price_to_power,
          name = "Price (EUR/kWh)"
        )
      ) +
      scale_color_manual(
        breaks = c("Grid usage", "PV usage", "Max PV available", "Energy price"),
        values = c(
          "Grid usage" = "orange",
          "PV usage" = "darkgreen",
          "Max PV available" = "lightgreen",
          "Energy price" = "darkgray"
        )
      ) +
      scale_fill_manual(
        values = c(
          "Grid usage" = "orange",
          "PV usage" = "darkgreen"
        ),
        guide = "none"
      ) +
      theme_minimal() +
      theme(
        legend.position = "bottom",
        legend.title = element_blank(),
        axis.text = element_text(size = 14),
        axis.title = element_text(size = 14),
        legend.text = element_text(size = 14),
        axis.title.y.right = element_text(color = "black"),
        axis.text.y.right = element_text(color = "black")
      )+ # stategy as title top center
      theme(
        plot.title = element_text(hjust = 0.5))
    
    print(p)
    
    ggsave(
      paste0(expriment_name, "_", strategy, ".pdf"),
      plot = p,
      width = 10,
      height = 6,
      dpi = 800
    )
  }
}