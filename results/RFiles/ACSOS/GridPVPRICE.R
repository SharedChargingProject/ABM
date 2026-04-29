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

strategy <- "SWRM"
expriment_name <- "ACSOS/ACSOS4"
file_name <- paste0(expriment_name, ".csv")

df <- read_csv(
  file_name,
  col_types = cols(.default = col_character())
)

# ------------------------------------------------------------
# raw power signals, no aggregation
# only Grid usage + Max PV available
# ------------------------------------------------------------
power_df <- df %>%
  filter(
    charging_column__strategy == strategy,
    agent == "energy_sandbox",
    field %in% c("power_output_grid_kW", "current_pv_power_kW")
  ) %>%
  transmute(
    time = as_datetime(suppressWarnings(as.numeric(time)), tz = "Europe/Vienna"),
    seed = seed,
    signal = case_when(
      field == "power_output_grid_kW" ~ "Grid usage",
      field == "current_pv_power_kW" ~ "Max PV available"
    ),
    value_kW = suppressWarnings(as.numeric(value))
  ) %>%
  filter(!is.na(time), !is.na(signal), !is.na(value_kW))

grid_df <- power_df %>%
  filter(signal == "Grid usage")

# PV availability is identical across seeds, so keep only unique points
pv_avail_df <- power_df %>%
  filter(signal == "Max PV available") %>%
  distinct(time, value_kW, .keep_all = TRUE)

# ------------------------------------------------------------
# raw price signal, no aggregation
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
  distinct(time, price_eur_kwh, .keep_all = TRUE)

# ------------------------------------------------------------
# secondary-axis scaling
# ------------------------------------------------------------
power_ymax <- max(
  c(grid_df$value_kW, pv_avail_df$value_kW),
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
  geom_step(
    data = grid_df,
    aes(x = time, y = value_kW, group = seed, color = "Grid usage"),
    linewidth = 0.8,
    alpha = 0.35
  ) +
  geom_step(
    data = pv_avail_df,
    aes(x = time, y = value_kW, color = "Max PV available"),
    linewidth = 1,
    linetype = "dotdash"
  ) +
  geom_step(
    data = price_df,
    aes(x = time, y = price_scaled, color = "Energy price"),
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
    breaks = c("Grid usage", "Max PV available", "Energy price"),
    values = c(
      "Grid usage" = "orange",
      "Max PV available" = "lightgreen",
      "Energy price" = "darkgray"
    )
  ) +
  theme_minimal() +
  theme(
    legend.position = "bottom",
    legend.title = element_blank(),
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 14),
    legend.text = element_text(size = 12),
    axis.title.y.right = element_text(color = "darkgray"),
    axis.text.y.right = element_text(color = "darkgray"),
    plot.title = element_text(hjust = 0.5)
  ) +
  ggtitle(paste0("Strategy: ", strategy))

print(p)

ggsave(
  paste0(strategy, "_grid_pvavail_price_raw_dual_axis.PNG"),
  plot = p,
  width = 10,
  height = 6,
  dpi = 300
)