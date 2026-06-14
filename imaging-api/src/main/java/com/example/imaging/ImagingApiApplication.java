package com.example.imaging;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableCaching
@EnableAsync
public class ImagingApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(ImagingApiApplication.class, args);
    }
}
