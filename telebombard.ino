#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <LiquidCrystal_I2C.h>
#include <wifi_credentials.h>

#define ARDUINO_USB_CDC_ON_BOOT 1

// builtin led
#define RGB_BRIGHTNESS 10 // Change white brightness (max 255)
#ifdef RGB_BUILTIN
#undef RGB_BUILTIN
#endif
#define RGB_BUILTIN 10

// button
#define BUTTON_PIN 2 // GPIO21 pin connected to button
int lastButtonState = HIGH; // the previous state from the input pin

int handleButton(int last) {
  int current = digitalRead(BUTTON_PIN);

  if(last == HIGH && current == LOW) {
    Serial.println("Owntone reset button pressed");
    if (WiFi.status() == WL_CONNECTED) {
      neopixelWrite(RGB_BUILTIN,0,0,RGB_BRIGHTNESS);
      delay(500);

      HTTPClient http;
      http.begin("http://192.168.1.39:3689/api/update");
      int status = http.PUT("");

      Serial.print("Status code: ");
      Serial.println(status);

      // For 204 No Content, http.getString() returns empty
      if (status == 204) {
        neopixelWrite(RGB_BUILTIN,RGB_BRIGHTNESS,0,0);
        Serial.println("Rescan triggered!");
      } else {
        Serial.println("Request failed.");
        neopixelWrite(RGB_BUILTIN,0,RGB_BRIGHTNESS,0);
      }

      delay(1000);
      http.end();
    }
    else {
      neopixelWrite(RGB_BUILTIN,0,RGB_BRIGHTNESS,0);
    }
  }
  neopixelWrite(RGB_BUILTIN,0,0,0);
  return current;
}

// potentiometer
#define POTENTIOMETER_PIN 3
int lastPotentiometerValue;

float floatMap(float x, float in_min, float in_max, float out_min, float out_max) {
  return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}

// lcd
#define I2C_SDA 4
#define I2C_SCL 5
LiquidCrystal_I2C lcd(0x27, 16, 2); // I2C address 0x27, 16 column and 2 rows

// lan


// -----------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println("\nConnected!");
  Serial.println(WiFi.localIP());

  // initialize the pushbutton pin as an pull-up input
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // set the ADC attenuation to 11 dB (up to ~3.3V input)
  analogSetAttenuation(ADC_11db);
  lastPotentiometerValue = analogRead(POTENTIOMETER_PIN);

  // lcd
  Wire.begin(I2C_SDA, I2C_SCL);
  lcd.init(); // initialize the lcd to use user defined I2C pins
	lcd.backlight();

	lcd.setCursor(3,0);
	lcd.print("Hello, world!");
	lcd.setCursor(2,1);
	lcd.print("Time is now");
}

int handlePotentiometer(int last) {
  int current = analogRead(POTENTIOMETER_PIN);
  if(abs(last - current) > 300) {
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("Volume:");
    lcd.setCursor(0,1);

    // char result[17]; // 16 chars + null terminator
    // int filled = (current * 16) / 4095;

    // for (int i = 0; i < 16; i++) {
    //     if (i < filled) {
    //         result[i] = '#';
    //     } else {
    //         result[i] = ' ';
    //     }
    // }
    // result[16] = '\0';  // terminate string
    // lcd.print(result);

    int totalPixels = (current * 16 * 5) / 4095; // 16 chars x 5 pixels

    for (int i = 0; i < 16; i++) {
        int pixels = totalPixels - i*5;
        if (pixels >= 5) lcd.write(byte(7)); // full block
        else if (pixels > 0) lcd.write(byte(pixels-1)); // partial
        else lcd.print(' ');  // empty
    }

    Serial.print("Analog: ");
    Serial.print(current);
    Serial.print(", Voltage: ");
    float currentVoltage = floatMap(current, 0, 4095, 0, 3.3);
    Serial.println(currentVoltage);
    delay(100);
    return current;
  }
  return last;
}

void loop() {
  //button
  lastButtonState = handleButton(lastButtonState);

  //potentiometer
  lastPotentiometerValue = handlePotentiometer(lastPotentiometerValue);
}
