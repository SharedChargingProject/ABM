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

THRD_KWH <- 9.36

# --- Define simulation start (Vienna) ---
t0 <- as.numeric(as.POSIXct("2023-06-05 06:00:00", tz = "Europe/Vienna"))

# --- helper: compute out for one csv + attach EV count ---
extract_out <- function(csv_file, n_evs) {
  df <- read_csv(csv_file, show_col_types = FALSE)
  
  df %>%
    filter(grepl("^ev_", agent)) %>%
    group_by(run_id, charging_column__strategy, agent) %>%
    summarise(
      initial_SoC = first(value[field == "initial_SoC"]),
      final_SoC   = first(value[field == "final_SoC"]),
      
      # charging start time (unix)
      t_connect = {
        t <- time[field == "CC_connected"]
        if (length(t)) min(t) else NA_real_
      },
      
      # first time threshold reached (unix)
      t_reached = {
        t <- time[field == "rec_energy" & value >= THRD_KWH]
        if (length(t)) min(t) else NA_real_
      },
      
      .groups = "drop"
    ) %>%
    mutate(
      # seconds since charging started
      t_THRD = t_reached - t_connect,
      
      n_evs = n_evs,
      n_evs_f = factor(n_evs, levels = c(30, 60, 120))
    ) %>%
    select(run_id, charging_column__strategy, agent, n_evs, n_evs_f, initial_SoC, final_SoC, t_THRD)
}

# ===================================================
# FAST CHARGING COLUMNS (FCC) =======================
#====================================================

out_all_fcc <- bind_rows(
  extract_out("avg_employee_1.csv", 30),
  extract_out("avg_employee_3.csv", 60),
  extract_out("avg_employee_5.csv", 120)
)

p_fcc_pdf <- out_all_fcc %>%
  filter(!is.na(t_THRD), is.finite(t_THRD)) %>%
  mutate(t_THRD_h = t_THRD / 60) %>%
  group_by(n_evs_f, charging_column__strategy) %>%
  do({
    d <- density(.$t_THRD_h)
    data.frame(
      x = d$x,
      y = d$y
    )
  }) %>%
  ungroup() %>%
  filter(y >= 0.01) %>%   # ← 2% density threshold
  ggplot(aes(
    x = x,
    y = y,
    colour = n_evs_f,
    linetype = charging_column__strategy
  )) +
  geom_line(linewidth = 0.71) +
  scale_linetype_manual(
    values = c("FCFS" = "solid", "SHRD" = "dashed")
  ) +
  labs(
    x = expression("Time to receive 9.36 kWh energy (minutes since " ~ t[connect] ~ ")"),
    y = "Probability density",
    colour = "Number of EVs",
    linetype = "Strategy"
  ) +
  theme_minimal(base_size = 13) +
  theme_bw()+
  theme(
    legend.position = "bottom",
    legend.justification = "center",
    legend.direction = "horizontal",
    legend.box = "horizontal",
    
    legend.text = element_text(size = 12),
    legend.key.size = unit(1.5, "lines"),
    
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 12),
    
    strip.text = element_text(size = 12)
  )

p_fcc_pdf
ggsave("TTR936_FCC_PDF.pdf", p_fcc_pdf, width = 8, height = 5)

p_fcc_cdf <- out_all_fcc %>%
  filter(!is.na(t_THRD), is.finite(t_THRD)) %>%
  mutate(t_THRD_h = t_THRD / 3600) %>%
  group_by(n_evs_f, charging_column__strategy) %>%
  do({
    d <- density(.$t_THRD_h)
    y <- cumsum(d$y)
    y <- y / max(y)  # normalize to 1
    data.frame(x = d$x, y = y)
  }) %>%
  ungroup() %>%
  ggplot(aes(x = x, y = y, colour = n_evs_f, linetype = charging_column__strategy)) +
  geom_line(linewidth = 0.71) +
  scale_linetype_manual(values = c("FCFS" = "solid", "SHRD" = "dashed")) +
  labs(
    x = expression("Time to receive 9.36 kWh energy (hours since " ~ t[connect] ~ ")"),
    y = "Cumulative probability",
    colour = "Number of EVs",
    linetype = "Strategy"
  ) +
  theme_minimal(base_size = 13) +
  theme(legend.position = "right", panel.grid.minor = element_blank())+
  theme_bw()+
  theme(
    legend.position = "bottom",
    legend.justification = "center",
    legend.direction = "horizontal",
    legend.box = "horizontal",
    
    legend.text = element_text(size = 12),
    legend.key.size = unit(1.5, "lines"),
    
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 12),
    
    strip.text = element_text(size = 12)
  )

p_fcc_cdf
ggsave("TTR936_FCC.pdf", p_fcc_cdf, width = 8, height = 5)

# ===================================================
# SLOW CHARHING COLUMNS (SCC) =======================
#====================================================

out_all_scc <- bind_rows(
  extract_out("avg_employee_7.csv", 30),
  extract_out("avg_employee_9.csv", 60),
  extract_out("avg_employee_11.csv", 120)
)

p_scc_cdf <- out_all_scc %>%
  filter(!is.na(t_THRD), is.finite(t_THRD)) %>%
  mutate(t_THRD_h = t_THRD / 3600) %>%
  group_by(n_evs_f, charging_column__strategy) %>%
  do({
    d <- density(.$t_THRD_h)
    y <- cumsum(d$y)
    y <- y / max(y)  # normalize to 1
    data.frame(x = d$x, y = y)
  }) %>%
  ungroup() %>%
  ggplot(aes(x = x, y = y, colour = n_evs_f, linetype = charging_column__strategy)) +
  geom_line(linewidth = 0.71) +
  scale_linetype_manual(values = c("FCFS" = "solid", "SHRD" = "dashed")) +
  labs(
    x = expression("Time to receive 9.36 kWh energy (hours since " ~ t[connect] ~ ")"),
    y = "Cumulative probability",
    colour = "Number of EVs",
    linetype = "Strategy"
  ) +
  theme_minimal(base_size = 13) +
  theme(legend.position = "right", panel.grid.minor = element_blank())+
  theme_bw()+
  theme(
    legend.position = "bottom",
    legend.justification = "center",
    legend.direction = "horizontal",
    legend.box = "horizontal",
    
    legend.text = element_text(size = 12),
    legend.key.size = unit(1.5, "lines"),
    
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 12),
    
    strip.text = element_text(size = 12)
  )

p_scc_cdf
ggsave("TTR936_SCC.pdf", p_scc_cdf, width = 8, height = 5)

# ===================================================
# APPEND: 3 COMPARISON PLOTS (30/60/120) ============
# Color = {FCC,SCC}, Linetype = Strategy ============
#====================================================

out_all_fcc2 <- out_all_fcc %>% mutate(case = "FCC")
out_all_scc2 <- out_all_scc %>% mutate(case = "SCC")

out_all_cases <- bind_rows(out_all_fcc2, out_all_scc2)

cdf_cases <- out_all_cases %>%
  filter(!is.na(t_THRD), is.finite(t_THRD)) %>%
  mutate(t_THRD_h = t_THRD / 3600) %>%
  group_by(case, n_evs_f, charging_column__strategy) %>%
  do({
    d <- density(.$t_THRD_h)
    y <- cumsum(d$y)
    y <- y / max(y)
    data.frame(x = d$x, y = y)
  }) %>%
  ungroup()

# 30 EVs
p_30 <- cdf_cases %>%
  filter(n_evs_f == "30") %>%
  ggplot(aes(x = x, y = y, colour = case, linetype = charging_column__strategy)) +
  geom_line(linewidth = 0.71) +
  scale_linetype_manual(values = c("FCFS" = "solid", "SHRD" = "dashed")) +
  labs(
    x = expression("Time to receive 9.36 kWh energy (hours since " ~ t[connect] ~ ")"),
    y = "Cumulative probability",
    colour = "Case",
    linetype = "Strategy"
  ) +
  theme_minimal(base_size = 13) +
  theme(legend.position = "right", panel.grid.minor = element_blank())+
  theme_bw()+
  theme(
    legend.position = "bottom",
    legend.justification = "center",
    legend.direction = "horizontal",
    legend.box = "horizontal",
    
    legend.text = element_text(size = 12),
    legend.key.size = unit(1.5, "lines"),
    
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 12),
    
    strip.text = element_text(size = 12)
  )

p_30
ggsave("TTR936_CMP_30.pdf", p_30, width = 8, height = 5)

# 60 EVs
p_60 <- cdf_cases %>%
  filter(n_evs_f == "60") %>%
  ggplot(aes(x = x, y = y, colour = case, linetype = charging_column__strategy)) +
  geom_line(linewidth = 0.71) +
  scale_linetype_manual(values = c("FCFS" = "solid", "SHRD" = "dashed")) +
  labs(
    x = expression("Time to receive 9.36 kWh energy (hours since " ~ t[connect] ~ ")"),
    y = "Cumulative probability",
    colour = "Case",
    linetype = "Strategy"
  ) +
  theme_minimal(base_size = 13) +
  theme(legend.position = "right", panel.grid.minor = element_blank())+
  theme_bw()+
  theme(
    legend.position = "bottom",
    legend.justification = "center",
    legend.direction = "horizontal",
    legend.box = "horizontal",
    
    legend.text = element_text(size = 12),
    legend.key.size = unit(1.5, "lines"),
    
    axis.text = element_text(size = 12),
    axis.title = element_text(size = 12),
    
    strip.text = element_text(size = 12)
  )

p_60
ggsave("TTR936_CMP_60.pdf", p_60, width = 8, height = 5)

# 120 EVs
p_120 <- cdf_cases %>%
  filter(n_evs_f == "120") %>%
  ggplot(aes(x = x, y = y, colour = case, linetype = charging_column__strategy)) +
  geom_line(linewidth = 0.71) +
  scale_linetype_manual(values = c("FCFS" = "solid", "SHRD" = "dashed")) +
  labs(
    x = expression("Time to receive 9.36 kWh energy (hours since " ~ t[connect] ~ ")"),
    y = "Cumulative probability",
    colour = "Case",
    linetype = "Strategy"
  ) +
  theme_minimal(base_size = 13) +
  theme(legend.position = "right", panel.grid.minor = element_blank())+
  theme_bw()+
    theme(
      legend.position = "bottom",
      legend.justification = "center",
      legend.direction = "horizontal",
      legend.box = "horizontal",
      
      legend.text = element_text(size = 12),
      legend.key.size = unit(1.5, "lines"),
      
      axis.text = element_text(size = 12),
      axis.title = element_text(size = 12),
      
      strip.text = element_text(size = 12)
    )

p_120
ggsave("TTR936_CMP_120.pdf", p_120, width = 8, height = 5)

