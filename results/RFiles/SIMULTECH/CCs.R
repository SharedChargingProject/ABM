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
library(stringr)
library(tibble)
library(purrr)
library(ggplot2)
library(tidyr)


files_map <- tibble(
  csv_file = c("avg_employee_1.csv","avg_employee_3.csv","avg_employee_5.csv",
               "avg_employee_7.csv","avg_employee_9.csv","avg_employee_11.csv"),
  n_evs    = c(30, 60, 120, 30, 60, 120),
  cc_type  = c("FCC","FCC","FCC","SCC","SCC","SCC")
)

pick_id_col <- function(df) {
  if ("run_id" %in% names(df)) return("run_id")
  if ("seed"   %in% names(df)) return("seed")
  stop("Neither run_id nor seed exists in the CSV.")
}

# NOTE: first arg name must match tibble column: csv_file
read_one <- function(csv_file, n_evs, cc_type) {
  df <- read_csv(csv_file, show_col_types = FALSE, col_types = cols(.default = col_character()))
  id_col <- pick_id_col(df)
  
  df %>%
    mutate(
      n_evs = n_evs,
      cc_type = cc_type,
      run = .data[[id_col]],
      time_num  = suppressWarnings(as.numeric(time)),
      value_num = suppressWarnings(as.numeric(value))
    )
}

df_all <- pmap_dfr(files_map, read_one)


# simulation length per (run, config)
sim_len <- df_all %>%
  filter(is.finite(time_num)) %>%
  group_by(cc_type, n_evs, run) %>%
  summarise(
    sim_len_sec = max(time_num, na.rm = TRUE) - min(time_num, na.rm = TRUE),
    .groups = "drop"
  )

# per-CC per-run charge time
cc_metrics <- df_all %>%
  filter(str_starts(agent, "charging_column_")) %>%
  filter(field == "log_charge_duration_sec") %>%
  group_by(cc_type, n_evs, run, charging_column__strategy, agent) %>%
  summarise(
    charge_time_sec = max(value_num, na.rm = TRUE),
    .groups = "drop"
  )

util_df <- cc_metrics %>%
  left_join(sim_len, by = c("cc_type", "n_evs", "run")) %>%
  mutate(
    util = charge_time_sec / sim_len_sec,
    n_evs_f = factor(n_evs, levels = c(30, 60, 120)),
    cc_type = factor(cc_type, levels = c("FCC","SCC"))
  ) %>%
  filter(is.finite(util), util >= 0)

# -----------------------
# plots: 1 per EV count
# -----------------------
plot_util_density <- function(n_target) {
  ggplot(util_df %>% filter(n_evs == n_target),
         aes(x = 100 * util,
             colour = cc_type,
             linetype = charging_column__strategy)) +
    geom_density(linewidth = 0.9, adjust = 1.0) +
    labs(
      x = "CC utilization (%)",
      y = "Density",
      colour = "CC type",
      linetype = "Strategy"
    ) +
    theme_bw()
}

p_u_30  <- plot_util_density(30)
p_u_60  <- plot_util_density(60)
p_u_120 <- plot_util_density(120)

p_u_30
p_u_60
p_u_120

ggsave("UTIL_DENS_30EV.pdf",  p_u_30,  width = 7.5, height = 4.5)
ggsave("UTIL_DENS_60EV.pdf",  p_u_60,  width = 7.5, height = 4.5)
ggsave("UTIL_DENS_120EV.pdf", p_u_120, width = 7.5, height = 4.5)


# ==========================================================
# HORIZONTAL STACKED BANDS — with idle % text
# ==========================================================

# per-CC final logs: charge + handshake (per run, per strategy, per CC)
cc_final <- df_all %>%
  filter(str_starts(agent, "charging_column_")) %>%
  filter(field %in% c("log_charge_duration_sec", "log_handshake_duration_sec")) %>%
  group_by(cc_type, n_evs, run, charging_column__strategy, agent, field) %>%
  summarise(v = max(value_num, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = field, values_from = v) %>%
  mutate(
    log_charge_duration_sec = coalesce(log_charge_duration_sec, 0),
    log_handshake_duration_sec = coalesce(log_handshake_duration_sec, 0)
  ) %>%
  left_join(sim_len, by = c("cc_type", "n_evs", "run"))

# --- average fractions per config (across CCs and runs) ---
bands_cfg <- cc_final %>%
  mutate(
    f_charge = log_charge_duration_sec / sim_len_sec,
    f_handshake = log_handshake_duration_sec / sim_len_sec,
    f_idle = pmax(0, 1 - f_charge - f_handshake)
  ) %>%
  group_by(cc_type, n_evs, charging_column__strategy) %>%
  summarise(
    charge = mean(f_charge, na.rm = TRUE),
    handshake = mean(f_handshake, na.rm = TRUE),
    idle = mean(f_idle, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  pivot_longer(cols = c(charge, handshake, idle), names_to = "state", values_to = "frac") %>%
  mutate(
    state = factor(state, levels = c("charge", "handshake", "idle")),
    n_evs = factor(n_evs, levels = c(30, 60, 120)),
    cc_type = factor(cc_type, levels = c("FCC", "SCC"))
  )
exp_order <- tidyr::crossing(
  n_evs = factor(c(30, 60, 120), levels = c(30, 60, 120)),
  cc_type = factor(c("FCC", "SCC"), levels = c("FCC", "SCC")),
  charging_column__strategy = factor(c("FCFS", "SHRD"), levels = c("FCFS", "SHRD"))
) %>%
  mutate(config = paste0(n_evs, "EV ", charging_column__strategy, " ", cc_type))

bands_all <- bands_cfg %>%
  mutate(
    n_evs = factor(n_evs, levels = c(30, 60, 120)),
    cc_type = factor(cc_type, levels = c("FCC", "SCC")),
    charging_column__strategy = factor(charging_column__strategy, levels = c("FCFS", "SHRD")),
    config = paste0(n_evs, "EV ", charging_column__strategy, " ", cc_type),
    config = factor(config, levels = exp_order$config)   # <-- enforce table order
  ) %>%
  arrange(config)

# stacked cumulative positions (unchanged)
bands_all <- bands_all %>%
  group_by(config) %>%
  arrange(state, .by_group = TRUE) %>%
  mutate(
    pct = 100 * frac,
    cum = cumsum(pct),
    xmin = lag(cum, default = 0),
    xmax = cum,
    xmid = (xmin + xmax) / 2
  ) %>%
  ungroup()

p_all_bands_h <- ggplot(bands_all, aes(y = config, x = pct, fill = state)) +
  geom_col(width = 0.7) +
  geom_text(
    data = bands_all %>% filter(state == "idle"),
    aes(x = 1, label = sprintf("%.1f%%", pct)),
    hjust = 0, color = "black", size = 3.8
  ) +
  scale_y_discrete(limits = rev(levels(bands_all$config))) +  # <-- Exp.1 at top
  scale_fill_manual(values = c(charge = "green3", handshake = "gold", idle = "grey85")) +
  labs(x = "utilization profile", y = NULL, fill = NULL) +
  theme_bw() +
  theme(
    legend.position = "bottom",
    legend.justification = "center",
    legend.direction = "horizontal",
    legend.box = "horizontal",
    legend.text = element_text(size = 12),
    legend.key.size = unit(0.5, "lines"),
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 12),
    strip.text = element_text(size = 12)
  )

p_all_bands_h
 ggsave("CC_STATE_BANDS.pdf",
       p_all_bands_h,
       width = 10,
       height = 6)
