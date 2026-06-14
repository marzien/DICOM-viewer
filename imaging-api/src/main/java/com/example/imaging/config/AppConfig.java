package com.example.imaging.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import io.minio.MinioClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;
import org.springframework.web.client.RestClient;

import java.util.Base64;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;

@Configuration
public class AppConfig {

    @Value("${orthanc.base-url}")
    private String orthancBaseUrl;

    @Value("${orthanc.username}")
    private String orthancUsername;

    @Value("${orthanc.password}")
    private String orthancPassword;

    @Value("${ai.inference.url}")
    private String aiInferenceUrl;

    @Value("${minio.endpoint}")
    private String minioEndpoint;

    @Value("${minio.access-key}")
    private String minioAccessKey;

    @Value("${minio.secret-key}")
    private String minioSecretKey;

    @Bean(name = "orthancRestClient")
    public RestClient orthancRestClient() {
        String credentials = Base64.getEncoder()
                .encodeToString((orthancUsername + ":" + orthancPassword).getBytes());
        return RestClient.builder()
                .baseUrl(orthancBaseUrl)
                .defaultHeader("Authorization", "Basic " + credentials)
                .build();
    }

    @Bean(name = "aiRestClient")
    public RestClient aiRestClient() {
        return RestClient.builder()
                .baseUrl(aiInferenceUrl)
                .build();
    }

    @Bean
    public MinioClient minioClient() {
        return MinioClient.builder()
                .endpoint(minioEndpoint)
                .credentials(minioAccessKey, minioSecretKey)
                .build();
    }

    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager("frames");
        manager.setCaffeine(Caffeine.newBuilder()
                .maximumSize(500)
                .expireAfterWrite(10, TimeUnit.MINUTES));
        return manager;
    }

    @Bean(name = "asyncExecutor")
    public Executor asyncExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(16);
        executor.setQueueCapacity(100);
        executor.setThreadNamePrefix("ai-job-");
        executor.initialize();
        return executor;
    }
}
