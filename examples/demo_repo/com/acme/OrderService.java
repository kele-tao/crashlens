package com.acme;

import java.util.List;

public class OrderService {
    public String firstSku(List<String> skus) {
        return skus.get(0).trim();
    }

    public static void main(String[] args) {
        System.out.println(new OrderService().firstSku(null));
    }
}
