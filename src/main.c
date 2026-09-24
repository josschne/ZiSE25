/*
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>

#include "display.h"
#include "buzzer.h"
#include "leds.h"
#include "utils.h"

#define TEMP_THRESHOLD_C  30       /* trip point in °C */
#define TEMP_THREAD_STACK 1024
#define THREAD_PRIORITY   5

LOG_MODULE_REGISTER(temp_alarm, LOG_LEVEL_INF);

/* The shared atomic flag: true when temp ≥ threshold */
atomic_t alarm_flag = ATOMIC_INIT(0);

/* BME280 sensor (first OKAY bosch,bme280 node) */
static const struct device * const bme_dev =
  DEVICE_DT_GET_ANY(bosch_bme280);

static int sensor_init (void)
{
  if (!device_is_ready(bme_dev))
  {
    LOG_ERR("BME280 device %p not ready", bme_dev);
    return -ENODEV;
  }

  LOG_INF("BME280 sensor %s ready", bme_dev->name);
  return 0;
}

/* -E> deliberate MC4.R17.12 1 function name is concatenated with '__init_'
   token */
SYS_INIT(sensor_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);

/*--- temp thread: fetch & log & display & set alarm_flag ---*/
/**
 * @implements SRS-07
 */
static void noreturn temp_thread_fn (void * arg1, void * arg2, void * arg3)
{
  ARG_UNUSED(arg1);
  ARG_UNUSED(arg2);
  ARG_UNUSED(arg3);

  struct sensor_value temp = {0};
  int                 ret;

  while (true)
  {
    ret = sensor_sample_fetch(bme_dev);

    if (ret != 0)
    {
      LOG_ERR("sensor_sample_fetch failed: %d", ret);
      k_sleep(K_SECONDS(1));
      continue;
    }

    ret = sensor_channel_get(bme_dev,
                             SENSOR_CHAN_AMBIENT_TEMP,
                             &temp);

    if (ret != 0)
    {
      LOG_ERR("sensor_channel_get failed: %d", ret);
      k_sleep(K_SECONDS(1));
      continue;
    }

    LOG_INF("Temp: %d.%06d °C",
            temp.val1,
            (temp.val2 < 0 ? -temp.val2 : temp.val2));

#if defined(CONFIG_APP_DISPLAY)
    /* build segments XX.YY */
    int deg = temp.val1;

    __ASSERT(deg >= 0 && deg <= 999, "unexpected val1");

    if (deg < 0)
    {
      deg = 0;
    }

    if (deg > 99)
    {
      deg = 99;
    }

    int hund = (temp.val2 >= 0 ? temp.val2 : -temp.val2) / 10000;

    if (hund > 99)
    {
      hund = 99;
    }

    uint8_t segs[4] =
    {
      tm1637_segment_map[deg / 10],
      tm1637_segment_map[deg % 10] | 0x80U,
      tm1637_segment_map[(hund / 10) % 10],
      tm1637_segment_map[hund % 10],
    };

    display_write(segs);

#endif /* CONFIG_APP_DISPLAY */

    /* threshold logic */
    bool above = (temp.val1 > TEMP_THRESHOLD_C) ||
                 (temp.val1 == TEMP_THRESHOLD_C && temp.val2 >= 0);

    if (above && (atomic_get(&alarm_flag) == 0))
    {
      atomic_set(&alarm_flag, 1);
      LOG_WRN("Threshold reached");
    }
    else if (!above && (atomic_get(&alarm_flag) != 0))
    {
      atomic_set(&alarm_flag, 0);
      LOG_INF("Back below threshold");
    }

    k_sleep(K_SECONDS(1));
  }
}

K_THREAD_DEFINE(temp_thread, TEMP_THREAD_STACK,
                &temp_thread_fn, NULL, NULL, NULL,
                THREAD_PRIORITY, 0, 0);

